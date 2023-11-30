from abc import abstractmethod as _abstractmethod, ABCMeta as _ABCMeta
from socket import socket as _socket, AF_INET as _AF_INET, SOCK_STREAM as _SOCK_STREAM
from threading import Lock as _Lock, Thread as _Thread
from typing import Self as _Self


class Service(object, metaclass=_ABCMeta):
    """
    `Service` is the prototype of every network service. This abstract class implements the procedure of multithread
     tasks.
    """
    def __init__(self, port: int):
        """
        :param port: the port on which the service listens
        """
        self._lock: _Lock = _Lock()
        self._port: int = port
        self._socket: _socket = _socket(_AF_INET, _SOCK_STREAM, proto=0)
        self._main_thread: _Thread | None = None

    @_abstractmethod
    def run(self, *args, **kwargs):
        """
        Override this method to define the specific workflow.
        :param args: args
        :param kwargs: kwargs
        """
        raise NotImplementedError

    def _run(self, *args, **kwargs):
        """
        This method is equivalent to `Service.run()`. It leaves a middle layer for possible features in subclasses.
        :param args: args passed to `Service.run()`
        :param kwargs: kwargs passed to `Service.run()`
        """
        self.run(*args, **kwargs)

    def _register_process(self, *args, **kwargs):
        """
        Register the multithread worker.
        :param args: args passed to `Service.run()`
        :param kwargs: kwargs passed to `Service.run()`
        """
        self._lock.acquire()
        if self._main_thread:
            raise RuntimeWarning("A service can only run once")
        try:
            self._main_thread = _Thread(name=f"service{hash(self)}", target=self._run, args=args, kwargs=kwargs)
        finally:
            self._lock.release()

    def _parallel_run(self, *args, **kwargs):
        """
        This method is similar to `Service._run()` except that it runs the workflow in a child thread.
        :param args: args passed to `Service.run()`
        :param kwargs: kwargs passed to `Service.run()`
        """
        self._register_process(*args, **kwargs)
        self._main_thread.start()

    def start(self, parallel: bool = False, *args, **kwargs) -> _Self:
        """
        This is the publicly exposed interface to start the service.
        :param parallel: True: main thread not blocked; False: main thread blocked
        :param args: args passed to `Service.run()`
        :param kwargs: kwargs passed to `Service.run()`
        :return: self
        """
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
    """
    `Connection` wraps the socket and provides fundamental functions.
    """
    def __init__(self, service: Service, socket: _socket, address: tuple[str, int], remainder_data: bytes = b""):
        """
        :param service: the service to which it belongs
        :param socket: the connection socket
        :param address: peer address
        :param remainder_data: message remain from last connection
        """
        self._service: Service = service
        self._socket: _socket = socket
        self._address: tuple[str, int] = address
        self._remainder: bytes = remainder_data

    def __str__(self) -> str:
        return self._address[0] + ":" + str(self._address[1])

    def closed(self) -> bool:
        """
        :return: True: the socket is closed; False: the socket is active
        """
        return self._socket.fileno() == -1

    def _require_open_socket(self, mandatory: bool = True) -> _socket:
        """
        Check if the socket is active and return it
        :param mandatory: True: an open socket is required; False: a closed socket is acceptable
        :return: the socket object
        """
        if mandatory and self.closed():
            raise IOError("An open socket is required")
        return self._socket

    def receive(self, chunk_size: int = 512) -> bytes | None:
        """
        :param chunk_size: chunk buffer size
        :return: message in bytes or None
        """
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
                msg += self._require_open_socket().recv(chunk_size)
            if (i := msg.find(b";")) != len(msg) - 1:
                self._remainder = msg[i + 1:]
                return msg[:i]
            return msg[:len(msg) - 1]
        except IOError:
            return

    def send(self, msg: bytes):
        """
        :param msg: message in bytes
        """
        self._require_open_socket().send(msg + b";")
        if msg == b"disconnect":
            self.close()

    def disconnect(self):
        """
        Request disconnection.
        """
        self.send(b"disconnect")

    def close(self):
        """
        Directly close the socket.
        """
        self._require_open_socket(False).close()


class Callback(object):
    def on_initialize(self, service: Service):
        pass

    def on_fail(self, service: Service, error: Exception):
        pass

    def on_connect(self, service: Service, connection: Connection):
        pass

    def on_receive(self, service: Service, msg: bytes):
        pass

    def on_disconnect(self, service: Service):
        pass


class Entity(Service, metaclass=_ABCMeta):
    """
    An `Entity` is a service with callback methods.
    """
    def __init__(self, port: int, callback: Callback):
        """
        :param port: the port on which the service listens
        :param callback: the callback interface
        """
        super().__init__(port)
        self.callback: Callback = callback

    def _stage(self, connection: Connection):
        while True:
            msg = connection.receive()
            if not msg or msg == b"disconnect":
                self.callback.on_disconnect(self)
                connection.close()
                return
            self.callback.on_receive(self, msg)

    def _run(self, *args, **kwargs):
        try:
            return super()._run(*args, **kwargs)
        except Exception as e:
            self.callback.on_fail(self, e)
