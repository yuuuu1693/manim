"""Backward-compatible adapter for the original image parser."""

from manimlib.ai.image_parser import parse_image as _parse_image

def parse_image(image_path):
    """
    解析图片，提取几何图形，返回和text_parser同样格式的数据
    返回: {"objects": [{"type":"circle"/"square"/"triangle"}], "actions":[] }
    """
    return _parse_image(image_path).to_dict()


if __name__ == "__main__":
    # 本地测试用
    res = parse_image("test.png")
    print(res)
