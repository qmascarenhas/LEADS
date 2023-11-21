from typing import Self as _Self
from threading import Lock as _Lock, Thread as _Thread
from abc import abstractmethod as _abstractmethod, ABCMeta as _ABCMeta
from socket import socket as _socket, error as _error, AF_INET as _AF_INET, SOCK_STREAM as _SOCK_STREAM


class Service(object, metaclass=_ABCMeta):
    def __init__(self, port: int):
        self._port: int = port
        self._socket: _socket = _socket(_AF_INET, _SOCK_STREAM)
        self._main_thread: _Thread | None = None
        self._lock: _Lock = _Lock()

    @_abstractmethod
    def _run(self, *args, **kwargs):
        raise NotImplementedError

    def _register_process(self, *args, **kwargs):
        if self._main_thread is not None:
            raise RuntimeWarning("A single `Server` instance cannot be run twice")
        self._lock.acquire()
        try:
            self._main_thread = _Thread(target=self._run, args=args, kwargs=kwargs)
        finally:
            self._lock.release()

    def _parallel_run(self, *args, **kwargs):
        self._register_process(*args, **kwargs)
        self._main_thread.start()

    def start(self, parallel: bool = False, *args, **kwargs) -> _Self:
        try:
            return self
        finally:
            if parallel:
                self._parallel_run(*args, **kwargs)
            else:
                self._run(*args, **kwargs)

    @_abstractmethod
    def kill(self):
        raise NotImplementedError


class Connection(object):
    def __init__(self, service: Service, socket: _socket, address: tuple[str, int], remainder_data: bytes = b""):
        self._service: Service = service
        self._socket: _socket = socket
        self._address: tuple[str, int] = address
        self._remainder: bytes = remainder_data

    def __str__(self) -> str:
        return self._address[0] + ":" + str(self._address[1])

    def closed(self) -> bool:
        try:
            self._socket.getpeername()
            return False
        except _error:
            return True

    def _require_open_socket(self, mandatory: bool = True) -> _socket:
        if mandatory and self.closed():
            raise IOError("An open socket is required")
        return self._socket

    def receive(self, block_size: int = 512) -> bytes | None:
        if self._remainder != b"":
            if (i := self._remainder.find(b";")) != len(self._remainder) - 1:
                msg = self._remainder[:i + 1]
                self._remainder = self._remainder[i:]
            else:
                msg = self._remainder[:i]
                self._remainder = b""
            return msg
        try:
            msg = b""
            while not msg.endswith(b";"):
                msg += self._require_open_socket().recv(block_size)
            if (i := msg.find(b";")) != len(msg) - 1:
                self._remainder = msg[i + 1:]
                return msg[:i]
            return msg[:len(msg) - 1]
        except IOError:
            return

    def send(self, msg: bytes):
        self._require_open_socket().send(msg + b";")
        if msg == b"disconnect":
            self.close()

    def disconnect(self):
        self.send(b"disconnect")

    def close(self):
        self._require_open_socket(False).close()


class Callback(object):
    def on_connect(self, service: Service, connection: Connection):
        pass

    def on_receive(self, service: Service, msg: bytes):
        pass

    def on_disconnect(self, service: Service):
        pass


class Entity(Service, metaclass=_ABCMeta):
    def __init__(self, port: int, callback: Callback):
        super().__init__(port)
        self.callback: Callback = callback

    def _stage(self, connection: Connection):
        while True:
            msg = connection.receive()
            if msg is None or msg == b"disconnect":
                self.callback.on_disconnect(self)
                connection.close()
                return
            self.callback.on_receive(self, msg)
