"""STUB tối giản cho ccxt — CHỈ để import không lỗi khi test offline.
Không dùng khi chạy ứng dụng thật — hãy `pip install ccxt`."""


class binance:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_ohlcv(self, *args, **kwargs):
        raise NotImplementedError("Stub ccxt — không gọi mạng thật trong test offline")
