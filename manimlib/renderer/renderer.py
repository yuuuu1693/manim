from __future__ import annotations

from manimlib.renderer.material import Material
from manimlib.utils.iterables import batch_by_comparison

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Iterable
    from manimlib.mobject.mobject import Mobject
    from manimlib.renderer.drawing import Drawing
    from manimlib.renderer.gpu import Gpu, RenderPass
    from manimlib.renderer.shared_buffer import SharedBuffer


# How many frames a sequence of draws has to hold before it is worth bundling. Making a bundle
# costs about half again what making the draws once does, and replaying it a fraction of that,
# so a sequence which settles for a moment pays for itself and one which never settles is left
# alone.
FRAMES_BEFORE_BUNDLING = 2


class Bundling(object):
    """
    When a frame's draws are worth gathering into a render bundle, and for how long the one
    gathered still says what this frame means.

    Anything which notices that a bundle would now draw the wrong thing says so with
    invalidate, rather than each such thing being remembered and asked about afterwards.
    """

    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.bundle: Any = None
        self.settled = 0
        self.stale = True

    def invalidate(self) -> None:
        self.stale = True

    def take(self, make: Callable[[], Any]) -> Any:
        """
        The bundle to replay this frame, or none where the draws have to be made afresh. Makes
        one where they have held still long enough to be worth it.
        """
        if self.stale:
            self.stale = False
            self.settled = 0
            self.bundle = None
        else:
            self.settled += 1
            if self.bundle is None and self.allowed \
                    and self.settled >= FRAMES_BEFORE_BUNDLING:
                self.bundle = make()
        return self.bundle


class Renderer(object):
    """
    What a frame draws, in the order it draws it: a drawing for each mobject holding points,
    each knowing the material which draws it.

    A frame is two walks of that list. The first writes every mobject's values into the shared
    buffers and settles everything else its draw needs; the second draws. They are separate
    because a write reaching the gpu partway through a render pass has no say over which draws
    see it.

    The second walk is gathered into a bundle once the first stops finding anything different
    to say, and replayed with one call for as long as that holds, see Bundling. A bundle holds
    the order of the draws, which stretch each reads, how many vertices each covers and which
    pipeline each runs, and reads the buffers afresh every time: so a scene whose mobjects only
    move, or fade, or are looked at from somewhere else, replays what it gathered.

    Consecutive mobjects which one draw could cover are gathered into runs first, see group, so
    what is written and drawn is a run at a time rather than a mobject at a time. A page of
    plain text is one run.

    Materials are kept for as long as the gpu, there being one per kind of mobject rather than
    per mobject.
    """

    # __init__：Renderer渲染器类构造方法，初始化渲染管线相关全部成员变量
    def __init__(self, gpu: Gpu, bundle: bool = True, together: bool = True):
        self.gpu = gpu # 绑定GPU设备对象，用于调用底层GPU接口
        self.may_merge = together # 设置是否允许合并绘制指令，减少GPU调用次数
        self.bundling = Bundling(allowed=bundle) # 创建批处理打包对象，控制图形批渲染功能
        self.materials: dict[tuple, Material] = dict() # 材质字典，缓存不同样式的材质
        self.drawings: dict[Mobject, Drawing] = dict() # 图形对象与绘制数据的映射表
        self.drawn: list[Drawing] = [] # 保存当前帧待绘制的绘制对象列表
        self.leaders: list[Drawing] = [] # 辅助标注类图形绘制对象列表
        self.run_lengths: tuple = () # 图形批次长度元组，用于批量渲染
        self.samples = gpu.samples # 获取GPU多重采样数量，控制抗锯齿效果

    # draw：Renderer渲染器核心绘制方法，负责一帧内所有图形的批处理渲染
    def draw(self, mobjects: Iterable[Mobject], attachments: dict) -> None:
        gpu = self.gpu # 获取底层GPU操作对象
        drawings = self.resolve(mobjects) # 将Mobject图形对象解析为绘制数据Drawing
        if drawings != self.drawn:
            self.bundling.invalidate() # 图形发生变化，使批渲染缓存失效
        self.drawn = drawings # 记录当前帧的绘制对象

        rebinds = gpu.rebinds # 保存GPU绑定状态标记
        gpu.begin_writes() # 开启GPU数据写入阶段
        regroup = False # 是否需要重新分组绘制的标记
        for drawing in drawings: # 遍历所有待绘制图形
            if drawing.write_uniforms(): # 向GPU写入着色器统一变量
                regroup = True # 变量变更，标记需要重新分组
            if drawing.invalidated:
                self.bundling.invalidate() # 图形数据失效，清空批渲染缓存
        # A frame where nothing which decides the runs moved keeps last frame's
        # 如果批缓存过期或者需要重分组，则重新对绘制对象分组
        if self.bundling.stale or regroup:
            lengths = self.group(drawings) # 按照材质分组图形，实现批渲染
            if lengths != self.run_lengths:
                self.bundling.invalidate()
            self.run_lengths = lengths
        for leader in self.leaders: # 遍历标注类辅助图形
            leader.write_records() # 写入辅助图形绘制记录
            if leader.invalidated:
                self.bundling.invalidate()
        gpu.end_writes() # 结束GPU数据写入阶段
        if gpu.rebinds != rebinds or gpu.samples != self.samples:
            self.bundling.invalidate() # GPU参数改变，使批渲染缓存失效
        self.samples = gpu.samples # 更新抗锯齿采样参数

        bundle = self.bundling.take(lambda: gpu.bundle(self.make_draws)) # 获取绘制指令批包
        with gpu.render_pass(attachments) as render_pass: # 开启一次GPU渲染通道
            if bundle is None:
                self.make_draws(render_pass) # 无缓存批包，实时执行绘制指令
            else:
                render_pass.replay(bundle) # 复用缓存批包，直接回放绘制指令，提升渲染性能

    def make_draws(self, render_pass: RenderPass) -> None:
        for leader in self.leaders:
            leader.draw(render_pass)

    # 注释：该方法用于将可连续绘制的Drawing对象合并批次，实现GPU批渲染
 #注释：满足相同材质、一致uniform变量的图形合并为一个绘制批次，减少GPU调用次数
    def group(self, drawings: list[Drawing]) -> tuple:
        """
        Gathers consecutive mobjects which one draw can cover: the same material, nothing about
        them which a draw settles per mobject, and the same uniforms, since a draw carries one
        block of them.

        Leaves the mobjects which draw in self.leaders, each holding the run it draws, and
        gives back how long each run came out, which is what says the gathering has moved.
        """
        # 判断是否允许合并批次，不允许合并则每个图形单独为一组
        if not self.may_merge:
            self.leaders = list(drawings)
            return (1,) * len(drawings)

        self.compare_uniforms(drawings) # 对比所有绘制对象的uniform着色器变量
        # 根据can_follow规则，对drawings进行批次分组
        runs = batch_by_comparison(
            drawings, lambda prev, drawing: drawing.can_follow(prev)
        )

        # Pull out first of each run as a leader
        # 提取每一组的第一个对象作为leader（批次代表对象）
        self.leaders = []
        lengths = []
        for run in runs:
            run[0].members = run if len(run) > 1 else None # 将同组其余对象挂载到leader
            self.leaders.append(run[0])
            lengths.append(len(run))
        return tuple(lengths) # 返回每个批次包含图形数量的元组

    def compare_uniforms(self, drawings: list[Drawing]) -> None:
        """
        Tells every mobject whether the one drawn before it holds the same uniforms, which is
        the last thing can_follow needs and the one thing not worth asking a pair at a time.

        Each mobject claimed a block of its uniform buffer as it was written, in drawing order,
        so one pass over a buffer answers for every mobject which took a block from it, see
        SharedBuffer.matching_claims. A mobject only ever reads its answer against one of its
        own material, and two of a material share a buffer with nothing claiming between them,
        so the block before a mobject's own is the block of the mobject before it.
        """
        matching: dict[SharedBuffer, list[bool]] = dict()
        for drawing in drawings:
            buffer = drawing.material.uniform_buffer
            claims = matching.get(buffer)
            if claims is None:
                claims = matching[buffer] = buffer.matching_claims()
            drawing.repeats_uniforms = claims[drawing.uniform_offset // buffer.window]

    # 注释该方法用于将场景中的Mobject图形对象集合，转换为GPU可识别的Drawing绘制对象列表
    # 会根据z_index深度值完成图形排序，过滤掉不需要渲染的空图形
    def resolve(self, mobjects: Iterable[Mobject]) -> list[Drawing]:
        """
        A drawing for every member of every family which has anything to draw, in drawing
        order, keeping the one it had where it has one. A member holding no points, a group
        say, is passed over, as is one whose kind has no shader to be drawn by.

        Mobjects asking to be drawn out of that order say so with a z_index.
        """
        held = self.drawings # 保存上一帧缓存的绘制对象
        self.drawings = dict() # 重置当前帧绘制对象字典
        drawn = [] # 存放最终解析完成的Drawing列表
        ascending = True # 标记z轴排序方向
        prev_z = 0 # 记录上一个图形的z深度值
        for mobject in mobjects: # 遍历所有传入的图形Mobject
            for mob in mobject.get_family(): # 遍历图形自身及其子对象（Group组合图形）
                drawing_class = mob.drawing_class # 获取该图形对应的绘制类
                if len(mob.data) == 0 or not drawing_class.draws(mob):
                    continue # 无顶点数据或者无着色器，跳过不渲染
                drawing = held.get(mob) # 尝试复用缓存里上一帧的Drawing对象
                if drawing is None or drawing.replacements is not mob.shader_code_replacements:
                    # 缓存不存在或者着色器发生变更，则新建Drawing对象
                    drawing = drawing_class(self.material_for(mob, drawing_class), mob)
                self.drawings[mob] = drawing # 将绘制对象存入字典缓存
                drawn.append(drawing) # 加入待渲染列表
                z = mob.z_index # 获取图形的深度序号z_index
                if z < prev_z:
                    ascending = False # 出现z值变小，说明顺序不是升序
                prev_z = z
        if not ascending:
            # 如果z轴乱序，按照z_index重新排序，处理图层遮挡
            drawn.sort(key=lambda drawing: drawing.mobject.z_index)
        return drawn # 返回解析、排序完成的Drawing列表

    def material_for(self, mobject: Mobject, drawing_class: type) -> Material:
        """
        What draws this mobject, shared with every mobject its key agrees with, see
        Drawing.key.
        """
        key = drawing_class.key(mobject)
        if key not in self.materials:
            self.materials[key] = Material(
                self.gpu, mobject, drawing_class.module_specs(mobject),
            )
        return self.materials[key]
