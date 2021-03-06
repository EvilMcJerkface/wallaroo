# Copyright 2018 The Wallaroo Authors.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
#  implied. See the License for the specific language governing
#  permissions and limitations under the License.

import argparse
import asynchat
import asyncore
from collections import namedtuple
from datetime import datetime
import inspect
import logging
import os
from select import select
import socket
import struct
import sys
import threading
import time
import traceback

# A note on import dependencies:
# This only works if `machida/lib/` is in your PYTHONNPATH. This is fine here
# because you can't use wallaroo without that anyway.
# Anyway, don't use relative imports here.
import wallaroo
from wallaroo import dt_to_timestamp
from  . import connector_wire_messages as cwm

# get a version comptible base metaclass
if sys.version_info.major == 2:
    from .base_meta2 import BaseMeta, abstractmethod
else:
    from .base_meta3 import BaseMeta, abstractmethod


class ConnectorError(Exception):
    pass


class ProtocolError(Exception):
    pass


def stream_message_decoder(func):
    wallaroo._validate_arity_compatability(func.__name__, func, 1)
    C = wallaroo._wallaroo_wrap(func.__name__, func, wallaroo.ConnectorDecoder)
    return C()


def stream_message_encoder(func):
    wallaroo._validate_arity_compatability(func.__name__, func, 1)
    C = wallaroo._wallaroo_wrap(func.__name__, func, wallaroo.ConnectorEncoder)
    return C()

def octet_message_decoder(func):
    wallaroo._validate_arity_compatability(func.__name__, func, 1)
    C = wallaroo._wallaroo_wrap(func.__name__, func, wallaroo.OctetDecoder)
    return C()


def octet_message_encoder(func):
    wallaroo._validate_arity_compatability(func.__name__, func, 1)
    C = wallaroo._wallaroo_wrap(func.__name__, func, wallaroo.OctetEncoder)
    return C()


class SourceConnectorConfig(object):
    def __init__(self, name, encoder, decoder, port, cookie,
                 max_credits, refill_credits, host='127.0.0.1'):
        self._name = name
        self._encoder = encoder
        self._decoder = decoder
        self._port = port
        self._cookie = cookie
        self._max_credits = max_credits
        self._refill_credits = refill_credits
        self._host = host
        logging.debug("{}: name {} encoder {} decoder {} max_credits {}"
            .format(self,name, encoder, decoder, max_credits))

    def to_tuple(self):
        return ("source_connector", self._name, self._host, str(self._port), self._encoder, self._decoder, self._cookie, self._max_credits, self._refill_credits)


class SinkConnectorConfig(object):
    def __init__(self, name, encoder, decoder, port, cookie, host='127.0.0.1'):
        self._name = name
        self._host = host
        self._port = port
        self._cookie = cookie
        self._encoder = encoder
        self._decoder = decoder

    def to_tuple(self):
        return ("sink_connector", self._name, self._host, str(self._port), self._encoder, self._decoder, self._cookie)


class BaseConnector(object):
    def __init__(self, args=None, required_params=[], optional_params=[]):
        params = parse_connector_args(args or sys.argv, required_params, optional_params)
        wallaroo_mod = __import__(params.application)
        application = wallaroo_mod.application_setup(args or sys.argv)
        source = None
        for stage in application[2]:
            for step in stage:
                if step[0] == 'source' and step[2][0] == 'source_connector' and step[2][1] == params.connector_name:
                    source = step[2]
        if source is None:
            raise RuntimeError("Unable to find a source connector with the name " + params.connector_name)
        (_, _name, host, port, encoder, _decoder, cookie, max_credits, refill_credits) = source
        self.params = params
        self._encoder = encoder
        self._host = host
        self._port = port
        self._cookie = cookie
        self._max_credits = max_credits
        self._refill_credits = refill_credits


class SourceConnector(BaseConnector):
    def __init__(self, args=None, required_params=['host', 'port'],
                 optional_params=[]):
        raise Exception("SourceConnector uses unsupported connector protocol, please use AtLeastOnceSourceConnector")
        super(SourceConnector, self).__init__(args, required_params,
                                              optional_params)
        self._conn = None
        self.count = 0

    def connect(self, host=None, port=None):
        while True:
            try:
                logging.debug("SourceConnector.connect: top")
                conn = socket.socket()
                conn.connect( (host or self._host, int(port or self._port)) )
                logging.debug("SourceConnector: Now connected on socket {}".format(conn.fileno()))
                self._conn = conn
                return
            except socket.error as err:
                if err.errno == socket.errno.ECONNREFUSED:
                    time.sleep(1)
                else:
                    raise

    def write(self, message, event_time=0, key=None):
        if self._conn == None:
            raise RuntimeError("Please call connect before writing")
        payload = self._encoder.encode(message, event_time, key)
        self._conn.sendall(payload)
        self.count += 1

Stream = namedtuple('Stream', ['id', 'name', 'point_of_ref', 'is_open'])


def _asyncore_loop(sentinel, timeout, socket_map):
    poll_fun = asyncore.poll

    try:
        while not sentinel.is_set():
            poll_fun(timeout=timeout, map=socket_map)
            time.sleep(timeout)
    except:
        logging.exception("_asyyncore_loop exited!")
    logging.info("_asyncore_loop exiting")
    if os.environ.get("ERROR_9_SHOULD_EXIT") is not None:
        ## See commit 5937dfe088
        ## Asyncore can have a race where a "error: ( 9, 'Bad file descriptor' )"
        ## happens, and the rest of the client hangs.  Until that bug has a
        ## work-around, we will force a Python exit here.
        os._exit(77)
    else:
        ## We are probably running in a Python test environment.  Do not
        ## halt everything here with a forced exit(); instead, let the test
        ## harness clean up.
        None


class AtLeastOnceSourceConnector(asynchat.async_chat, BaseConnector, BaseMeta):
    def __init__(self, version, cookie, program_name, instance_name,
                 host, port, delay=0):

        self.data = None
        # connection details are given from the base
        self._host = host
        self._port = int(port)  # convert port to int
        self.credits = 0
        self.version = version
        self.cookie = cookie
        self.program_name = program_name
        self.instance_name = instance_name
        self._delay = delay
        self._previous_ts = 0

        self._write_lock = threading.Lock()

        # Stream details
        # live streams for this connection
        self._streams = {}  # {stream_id: {'stream': Stream, 'por': por}}
        self._pending_eos = {}  # {stream_id: point_of_ref}
        self._retry_notify = {} # {stream_id: Stream}

        self.handshake_complete = False
        self.in_buffer = []
        self.out_buffer = []
        self.reading_header = True
        self.set_terminator(4) # first frame header
        self.error = None

        # asyncore details
        # Start a select-poll loop with an empty map
        # as we connect, we will add the socket to the map once the
        # synchronous handshake part is complete
        self._socket_map = {}
        self._asyncore_loop_timeout = 0.000001
        self._loop_sentinel = threading.Event()
        self._loop = None
        self._async_init = False

        self._sent = 0
        self._in_reconnect_loop = False
        self._connect_count = 0

        # allow the user to do a join(timeout=0)
        self.stopped = threading.Event()
        print("version {} cookie {} program_name {} instance_name {} host {} port {} delay {}".format(version, cookie, program_name, instance_name, host, port, delay))

    def join(self, timeout=None):
        """
        Block until all sources have been exhausted or the timeout elapses
        if provided. If no timeout is provided this may block forever.
        """
        # wait for this
        dt = 0.0001
        if timeout is not None:
            if dt > timeout:
                dt == timeout
        while True:
            self.stopped.wait(dt)
            if self.stopped.is_set():
                break
            else:
                time.sleep(dt)
        return self.error

    #############################################
    # asyncore loop to run in background thread #
    #############################################
    def _stop_asyncore_loop(self):
        logging.debug("_stop_asyncore_loop")
        self._loop_sentinel.set()
        self.discard_buffers()

    def _start_asyncore_loop(self):
        self._loop_sentinel.clear()
        self._loop = threading.Thread(target = _asyncore_loop,
                                      args = (self._loop_sentinel,
                                              self._asyncore_loop_timeout,
                                              self._socket_map))
        self._loop.daemon = True
        self._loop.start()

    ###########################
    # Incoming communications #
    ###########################

    def collect_incoming_data(self, data):
        """Buffer the data"""
        self.in_buffer.append(data)

    def found_terminator(self):
        """Data is going to be in two parts:
        1. a 32-bit unsigned integer length header
        2. a payload of the size specified by (1)
        """
        if self.reading_header:
            # Read the header and set the terminator size for the payload
            self.reading_header = False
            h = struct.unpack(">I", b"".join(self.in_buffer))[0]
            self.in_buffer = []
            self.set_terminator(h)
        else:
            # Read the payload and pass it to _handle_frame
            self.set_terminator(4) # read next frame header
            self.reading_header = True
            frame = b"".join(self.in_buffer)
            self.in_buffer = []
            self._handle_frame(frame)

    def _handle_frame(self, frame):
        msg = cwm.Frame.decode(frame)
        # Ok, Error, NotifyAck, Ack, Restart
        if isinstance(msg, cwm.Ok):
            self._handle_ok(msg)
        elif isinstance(msg, cwm.Error):
            # Got error message from worker
            # close the connection and pass msg to the error handler but only
            # if not in handshake. If in handshake, let the initiate_handshake
            # function deal with this.
            if not self.in_handshake:
                self.close()
            raise ConnectorError(msg.message)
        elif isinstance(msg, cwm.NotifyAck):
            self._handle_notify_ack(msg)
        elif isinstance(msg, cwm.Ack):
            self._handle_ack(msg)
        elif isinstance(msg, cwm.Restart):
            self.handle_restart(msg)
        # messages that should only go connector->wallaroo
        # Notify, Hello, Message
        elif isinstance(msg, (cwm.Hello, cwm.Message, cwm.EosMessage, cwm.Notify)):
            # send error to wallaroo then shutdown and raise a protocol
            # exception
            try:
                self.error("Received an illegal message on the connector"
                           "side: {}".format(msg))
            except TimeoutError:
                pass
            raise ProtocolError(
                "{} should never be received at the connector.".format(msg))
        else: # handle unknown messages
            self.handle_invalid_message(msg, close=False)

    def _handle_ok(self, msg):
        if not self.in_handshake:
            self.close()
            raise ProtocolError("Got an Ok message outside of a"
                                " handshake")
        else:
            # deposit the credits
            self.credits += msg.initial_credits
            # set handshake_complete
            self.handshake_complete = True
            # set terminator to 4 to expect the next message's header
            self.set_terminator(4)

    def _handle_notify_ack(self, msg):
        logging.debug("NOTIFYack {}".format(msg))
        old = self._streams.get(msg.stream_id, None)
        if old is not None:
            new = Stream(old.id, old.name, msg.point_of_ref,
                         msg.notify_success)
            self._streams[old.id] = new
            self.stream_added(new)
            if new.is_open:
                self.stream_opened(new)
            else:
                logging.info("Stream {} id {} added to _retry_notify".format(old.name, msg.stream_id))
                self._retry_notify[msg.stream_id] = new
        else:
            # shouldn't get an ack for a stream we never notified
            # but it's not strictly an error, so don't crash
            logging.warning("received a NotifyAck for a stream that wasn't"
                " notified: {}".format(msg))

    def _handle_ack(self, msg):
        self.credits += msg.credits
        for (stream_id, point_of_ref) in msg.acks:
            # Try to get old stream data
            old = self._streams.get(stream_id, None)
            if old:
                if point_of_ref != old.point_of_ref:
                    new = Stream(stream_id, old.name, point_of_ref,
                                 old.is_open)
                    self._streams[stream_id] = new
                else:
                    new = old
                self.stream_acked(new)
        # Use this ack as a substitute for a timer that will
        # trigger retrying these stream ID notifications.
        for stream in self._retry_notify.values():
            logging.info("_retry_notify for {} id {}".format(stream.name, stream.id))
            self.notify(stream.id, stream.name, stream.point_of_ref)
        self._retry_notify = {}

    ##########################
    # Outoing communications #
    ##########################

    def connect(self):
        self.handshake_complete = False
        while True:
            try:
                logging.debug("AtLeastOnceSourceConnector.connect: top")
                conn = socket.socket()
                conn.connect( (self._host, self._port) )
            except Exception as err:
                logging.error("Failed to connect to {}:{}".format(self._host,
                    self._port))
                self.error = err
                if (self._connect_count == 1) or (not self._in_reconnect_loop):
                    ## Only stop the thread if the connect failure
                    ## was on our first attempt.
                    self.stopped.set()
                    raise err
                else:
                    time.sleep(1.0)
                    continue
            break
        logging.debug("Now connected on socket {}".format(conn.fileno()))
        self._conn = conn
        self._connect_count = self._connect_count + 1
        self._conn.setblocking(1) # Set socket to blocking mode

        self.in_handshake = True
        hello = cwm.Hello(self.version, self.cookie, self.program_name,
                          self.instance_name)
        data = cwm.Frame.encode(hello)
        self._conn.sendall(data)
        if self.data is not None:
            self.data.append(data)
        header_bytes = self._conn.recv(4)
        frame_size = struct.unpack('>I', header_bytes)[0]
        frame = self._conn.recv(frame_size)
        try:
            self._handle_frame(frame)
            logging.debug("connect: Socket {} _handle_frame done".format(self._conn.fileno()))
        except Exception as err:
            # close the connection and raise the error
            logging.debug("Socket {} exception {}".format(self._conn, err))
            self._conn.close()
            self._conn = None
            raise err
        # set socket to nonblocking
        self._conn.setblocking(0)
        # handshake complete: initialize async_chat
        self._start_asyncore_loop()
        if not self._async_init:
            self._async_init = True
            asynchat.async_chat.__init__(self,
                                         sock=self._conn,
                                         map=self._socket_map)
        self.set_socket(self._conn)
        logging.debug("Socket {} now ready".format(self._conn.fileno()))

    def handle_write(self):
        """
        If class has `__next__` method, this will consume from it
        while credits are available.
        If no `__next__` is provided, behaviour is semi-synchronous in that
        users must call `.write(msg)` directly in their own code, as well as
        `shutdown()` to ensure the outgoing queue is flushed.
        """
        with self._write_lock:
            if hasattr(self, '__next__'):
                # if delay is non-zero, return None if not enough time has elapsed
                if self._delay > 0:
                    t = time.time()
                    if t - self._previous_ts < self._delay:
                        return None
                    self._previous_ts = t
                    # continue
                try:
                    while self.credits > 0:
                        msg = self.__next__()
                        #if msg is not None: logging.debug("ITER msg = {}".format(msg))
                        if msg:
                            self.write(msg)
                        else:
                            break
                    self.initiate_send()
                except StopIteration:
                    self.initiate_send()
                    self.shutdown()
            else:
                self.initiate_send()

    def shutdown(self, error=None):
        logging.info("AtLeastOnceConnector.shutdown(error={})".format(error))
        if self._async_init:
            self.del_channel(self._socket_map) # remove the connection from asyncore loop
        self._stop_asyncore_loop()
        try:
            self._conn.setblocking(1)
        except:
            pass
        if error is None:
            # If this is a clean shutdown, try to synchronously send any
            # remaining data that was queued
            try:
                while self.producer_fifo:
                    self._conn.sendall(self.producer_fifo.popleft())
            except:
                pass
        if isinstance(error, cwm.Error):
            # If this is an error, synchronously send the error message
            try:
                self._conn.sendall(cwm.Frame.encode(error))
            except:
                pass
        try:
            self._conn.close()
        except:
            pass
        self._conn = None
        self.stopped.set()

    def writable(self):
        return self.credits >= 0

    def write(self, msg):
        if isinstance(msg, cwm.Message):
            # TODO: what to do when stream is closed?
            # For now: if stream isn't open (or doesn't exist), raise error
            # In the future, maybe this should automatically send a notify
            try:
                if self._streams[msg.stream_id].is_open:
                    ##logging.debug("write: encode: {}".format(msg))
                    data = cwm.Frame.encode(msg)
                    self._write(data)
                    # use up 1 credit
                    self.credits -= 1
                else:
                    raise
            except:
                raise ProtocolError("Message {} cannot be sent. Stream ({}) is "
                                    "not in an open state. Use notify() to "
                                    "open it."
                                    .format(msg, msg.stream_id))
        elif isinstance(msg, cwm.Notify):
            # write the message
            data = cwm.Frame.encode(msg)
            self._write(data)
            # use up 1 credit
            self.credits -= 1
        elif isinstance(msg, (cwm.EosMessage, cwm.Error)):
            # write the message
            data = cwm.Frame.encode(msg)
            self._write(data)
        else:
            raise ProtocolError("Can only send message types {{Notify, "
                                "Message, EosMessage, Error}}. Received {}".format(msg))

    def _write(self, data):
        """
        Replaces asynchat.async_chat.push, which does a synchronous send
        i.e. without calling `initiate_send()` at the end
        """
        self._sent += 1
        self.producer_fifo.append(data)

    def initiate_send(self):
        if self.connected:
            # collect data up to 65kb in size, send, repeat, until empty
            obs = self.ac_out_buffer_size
            q = self.producer_fifo
            data = []
            data_len = 0
            while q:
                b = q.popleft()
                if b is None:
                    self.handle_close()
                    return
                elif not b:
                    continue
                if not isinstance(b, bytes):
                    b = b.encode()
                if data_len + len(b) > obs:
                    joined = b''.join(data)
                    if len(joined) > 0:
                        res = self._send(joined)
                        if res != len(joined):
                            logging.info("initiate_send: socket send 1 returned {}".format(res))
                            return
                        data = [b]
                        data_len = len(b)
                else:
                    data.append(b)
                    data_len += len(b)
            if data:
                joined = b''.join(data)
                res = self._send(joined)
                if res != len(joined):
                    logging.info("initiate_send: socket send 2 returned {}".format(res))
                    return

    def _send(self, data):
        try:
            # This is the call to asyncore that actually writes to the socket
            res = self.send(data)
            if self.data is not None:
                self.data.append(data)
            return res
        except OSError:
            return self.handle_error()

    def pending_sends(self):
        """
        Are there any pending sends
        """
        if len(self.producer_fifo) > 0:
            return True
        else:
            return False

    def error(self, message):
        logging.warning("Sending error message: {}".format(message))
        self.shutdown(error=message)

    def notify(self, stream_id, stream_name=None, point_of_ref=None):
        old = self._streams.get(stream_id, None)
        if old:
            if point_of_ref is None:
                raise ConnectorError("Cannot update a stream without a valid "
                                     "point_of_ref value")
            new = Stream(stream_id,
                         old.name if old is not None else stream_name,
                         (point_of_ref if point_of_ref is not None else
                          old.point_of_ref),
                         old.is_open)
        else:
            if stream_name is None:
                raise ConnectorError("Cannot notify a new stream without "
                                     "a Stream name!")
            new = Stream(stream_id,
                         stream_name,
                         0 if point_of_ref is None else point_of_ref,
                         False)

        # update locally and call stream_added
        self._streams[new.id] = new
        self.stream_added(new)

        # send to wallaroo worker
        logging.debug("sending NOTIFY: {} on {}".format(cwm.Notify(new.id, new.name, new.point_of_ref), self._conn))
        self.write(cwm.Notify(new.id,
                              new.name,
                              new.point_of_ref))

    def end_of_stream(self, stream_id):
        """
        Send an EOS message for a stream_id.
        """
        # TODO: Wallaroo needs to ack and connector should implement a
        # stream_ended(stream) method.
        # Without this, there is a race condition around end of streams and
        # restarts which can result in the tail end of a stream not being resent
        # if it was EOSd before a restart, but the rollback is to before the EOS.
        msg = cwm.EosMessage(
            stream_id = stream_id)
        logging.info("Sending End of Stream {}".format(msg))
        self.write(msg)

    ###########################
    # User extensible methods #
    ###########################

    def handle_restarted(self, streams):
        """
        Logic to execute after successfully completing a restart

        The default is to send a new notify for every known stream.
        User may override this to provide their own logic based on the state
        of their sources.
        """
        # if restarting, send new notifys for existing streams to reopen them
        for stream in streams.values():
            self.notify(stream.id, stream.name, stream.point_of_ref)

    def handle_invalid_message(self, msg):
        logging.warning(ProtocolError(
            "Received an unrecognized message: {}".format(msg)))

    def handle_restart(self, msg):
        logging.warning("Received RESTART message. Closing streams and "
            "reinitiating handshake.")

        self._close_common()

        # optionally update target host and port
        if msg.address:
            logging.info("Updating target address from {}:{} to {}"
                .format(self._host, self._port, msg.address))
            host, port = msg.address.split(':')
            port = int(port)
            self._host = host
            self._port = port

        # Raise an exception rather than burrow down the stack even further.
        raise OSError(socket.errno.ECONNRESET)

    def _close_common(self):
        # reset credits
        self.credits = 0
        # close connection
        self._stop_asyncore_loop()
        logging.debug("Removing socket from asyncore map")
        if self._async_init:
            self.del_channel(self._socket_map) # remove the connection from asyncore loop
        ## For future asynchat/asyncore threads, use a different work map
        self._socket_map = {}

        logging.debug("Closing socket {}".format(self._conn.fileno()))
        self._conn.close()
        self._conn = None
        # close streams
        for sid, stream in self._streams.items():
            if stream.is_open:
                new = Stream(stream.id, stream.name, stream.point_of_ref, False)
                self._streams[sid] = new
                self.stream_closed(new)

        logging.debug("Popping the producer_fifo")
        c = 0
        while self.producer_fifo:
            self.producer_fifo.popleft()
            c = c + 1
        logging.debug("Popping the producer_fifo: count = {}".format(c))
        self.discard_buffers()
        self._retry_notify = {}

    def _reconnect_common(self):
        # try to connect again
        self._in_reconnect_loop = True
        retry_errno = [socket.errno.ECONNREFUSED, socket.errno.ECONNRESET]
        while True:
            if self._conn is not None:
                # We are already connected
                logging.debug("_reconnect_common: already connected with {}".format(self._conn))
                return
            try:
                logging.debug("AtLeastOnceSourceConnector: _reconnect_common: top")
                self.connect()
                logging.debug("AtLeastOnceSourceConnector: Now connected on socket {}".format(self._conn.fileno()))
                self._in_reconnect_loop = False
                self.handle_restarted(self._streams)
                break
            except socket.error as err:
                self._conn = None
                if err.errno in retry_errno:
                    logging.debug("_reconnect_common: {}".format(err))
                    time.sleep(1.0)
                    continue
                else:
                    logging.debug("_reconnect_common: else {}".format(err))
            except Exception as err:
                logging.error("_reconnect_common: connect failed: {}".format(err))
                raise

    def handle_close(self):
        logging.error("handle_close")
        self._close_common()
        time.sleep(0.10)
        self._reconnect_common()

    def handle_error(self):
        """
        Default error handler: print a normal error traceback to sys.stderr
        and close the connection.

        Users may override this with custom handlers

        e.g. trigger a callback in the user class to stop a TCP server

        ```python
        class MyTCPServer(AsyncClient):
            def handle_error(self):
                # print the error using the subclass method
                super(MyTCPServer, self).handle_error()
                # Stop MyTCPServer as well
                self.stop_server()
        ```
        """
        _type, _value, _traceback = sys.exc_info()
        exc_text = ''.join(
                traceback.format_exception(_type, _value, _traceback)).strip()
        logging.error("Closing the connection after encountering an"
                      " error:\n%s", exc_text)
        if self._in_reconnect_loop:
            logging.debug("Let's reconnect")
            self._reconnect_common()
            return

        self.error = _value
        self.close()

    ########################
    # User defined methods #
    ########################

    def stream_added(self, stream):
        """
        Action to take when a new stream is added [optional]
        """
        pass

    def stream_removed(self, stream):
        """
        Action to take when a stream is removed [optional]
        """
        pass

    @abstractmethod
    def stream_opened(self, stream):
        """
        Action to take when a stream status changes from closed to open
        [required]
        """
        raise NotImplementedError

    @abstractmethod
    def stream_closed(self, stream):
        """
        Action to take when a stream status changes from open to closed
        [required]
        """
        raise NotImplementedError

    @abstractmethod
    def stream_acked(self, stream):
        """
        Action to take when a stream's point of reference is updated
        [required]
        """
        raise NotImplementedError


class SinkConnector(object):
    def __init__(self, args=None, required_params=[], optional_params=[]):
        params = parse_connector_args(args or sys.argv, required_params, optional_params)
        wallaroo_mod = __import__(params.application)
        application = wallaroo_mod.application_setup(args or sys.argv)
        sink = None
        for stage in application[2]:
            for step in stage:
                if step[0] == 'to_sink' and step[1][0] == 'sink_connector' and step[1][1] == params.connector_name:
                    sink = step[1]
        if sink is None:
            raise RuntimeError("Unable to find a sink connector with the name " + params.connector_name)
        (_, _name, host, port, _encoder, decoder, cookie) = sink
        self.params = params
        self._decoder = decoder
        self._host = host
        self._port = port
        self._cookie = cookie
        self._acceptor = None
        self._connections = []
        self._buffers = {}
        self._pending = []

    def listen(self, host=None, port=None, backlog=0):
        acceptor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        acceptor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        acceptor.bind((host or self._host, int(port or self._port)))
        acceptor.listen(backlog)
        self._acceptor = acceptor
        self._connections.append(acceptor)

    def read(self, timeout=None):
        while True:
            for socket in self._pending:
                ok, message = self._read_one(socket)
                if ok: return message
            self._select_any(timeout)

    def _select_any(self, timeout=None):
        readable, _, exceptional = select(self._connections, [], self._connections, timeout)
        for socket in exceptional:
            if socket is self._acceptor:
                socket.close()
                raise UnexpectedSocketError()
            else:
                self._teardown_connection(socket)
        for socket in readable:
            if socket is self._acceptor:
                conn, _addr = socket.accept()
                self._setup_connection(conn)
            else:
                buffered = self._buffers[socket] + socket.recv(4096)
                self._buffers[socket] = buffered
                self._pending.append(socket)

    def _read_one(self, socket):
        buffered = self._buffers[socket]
        header_len = self._decoder.header_length()
        if len(buffered) < header_len:
            self._buffers[socket] = buffered
            return (False, None)
        expected = self._decoder.payload_length(buffered[:header_len])
        if len(buffered) < header_len + expected:
            self._buffers[socket] = buffered
            return (False, None)
        data = buffered[header_len:header_len+expected]
        buffered = buffered[header_len + expected:]
        self._buffers[socket] = buffered
        if len(buffered) < header_len:
            self._pending.remove(socket)
        return (True, self._decoder.decode(data))

    def _setup_connection(self, conn):
        conn.setblocking(0)
        self._connections.append(conn)
        self._buffers[conn] = b""

    def _teardown_connection(self, conn):
        self._connections.remove(conn)
        del self._buffers[conn]
        conn.close()


class UnexpectedSocketError(Exception):
    pass


def parse_connector_args(args, required_params=[], optional_params=[]):
    connector_prefix = _parse_connector_prefix(args) or 'CONNECTOR_NAME'
    parser = argparse.ArgumentParser()
    parser.add_argument('--application-module', dest='application', required=True)
    parser.add_argument('--connector', dest='connector_name', required=True)
    for key in required_params:
        parser.add_argument('--{}-{}'.format(connector_prefix, key), dest=key, required=True)
    for key in optional_params:
        parser.add_argument('--{}-{}'.format(connector_prefix, key), dest=key)
    params = parser.parse_known_args(args)[0]
    return params


def _parse_connector_prefix(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('--connector', dest='connector_name')
    params = parser.parse_known_args(args)[0]
    return params.connector_name
