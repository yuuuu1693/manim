class AIParser:
    """
    未来接入大模型接口。
    AI 输出统一转换为：
    {
        "objects":[],
        "actions":[]
    }
    """

    def analyze(self, text):
        raise NotImplementedError
