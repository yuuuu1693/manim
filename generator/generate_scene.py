from .text_parser import parse_text
from .image_parser import parse_image
from .code_generator import generate_code
import os


def create_scene(prompt_text=None, image_file=None):
    """
    两种模式：
    1. prompt_text不为None：自然语言文本生成
    2. image_file不为None：图片识图生成
    """
    if image_file is not None:
        data = parse_image(image_file)
    elif prompt_text is not None:
        data = parse_text(prompt_text)
    else:
        raise Exception("需要传入文本描述或者图片路径")

    code = generate_code(data)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(os.path.dirname(out_dir), "generated_scene.py")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(code)
    return out_path

if __name__ == "__main__":
    text = input("请输入动画需求：")
    print(create_scene(text))
