
"""
A socket bridge implementation was borrowed from this repository https://github.com/aploium/shootback
I just little simplified it.
"""  
#!/usr/bin/env python
# coding=utf-8
import collections
import warnings
import traceback
import datetime
import logging
import threading
import time

try:
    import selectors
    from selectors import EVENT_READ, EVENT_WRITE

    EVENT_READ_WRITE = EVENT_READ | EVENT_WRITE
except ImportError:
    import select

    warnings.warn('selectors module not available, fallback to select')
    selectors = None

# socket recv buffer, 16384 bytes
RECV_BUFFER_SIZE = 2 ** 14


def fmt_addr(socket):
    """(host, int(port)) --> "host:port" """
    return "{}:{}".format(*socket)

def try_close(connection):
    try:
        connection.close()
    except:
        pass


class SocketBridge ():

    def __init__ (self, terminate_callback = None, timeout = 60):
        self.work = True
        self.connections = set()  # holds all sockets
        self.map = {}  # holds sockets pairs
        self.callback =  terminate_callback # holds callback
        self.send_buff = {}  # buff one packet for those sending too-fast socket
        self.timeout_sec = timeout
        self.timeout_counter = 0
        self.delay = 0.1
        if selectors:
            self.selector = selectors.DefaultSelector()
        else:
            self.selector = None
        
        

    def add_pair (self, conn1, conn2):
        """
        transfer anything between two sockets
        :type conn1: socket.socket
        :type conn2: socket.socket
        :param callback: callback in connection finish
        :type callback: Callable
        """
        # change to non-blocking
        # we use select or epoll to notice when data is ready
        conn1.setblocking(False)
        conn2.setblocking(False)

        # mark as readable+writable
        self.connections.add(conn1)
        self.connections.add(conn2)

        # record sockets pairs
        self.map[conn1] = conn2
        self.map[conn2] = conn1
            
        if self.selector:
            self.selector.register(conn1, EVENT_READ_WRITE)
            self.selector.register(conn2, EVENT_READ_WRITE)

        logging.debug("New pair added. Total {} sockets in bridge".format(len(self.connections)))


    def start_as_daemon(self):
        t = threading.Thread(target=self.start, name="socketBridge")
        t.daemon = True
        t.start()
        logging.info("SocketBridge daemon started")
        return t

    def start(self):
        while self.work:
            try:
                self._start()
            except:
                logging.error("FATAL ERROR! SocketBridge failed {}".format(
                    traceback.format_exc()
                ))


    def _start(self): 
        self._last_success_read = datetime.datetime.now() 
        while self.work:
            # Check if timeout reached
            if (datetime.datetime.now() - self._last_success_read).total_seconds() >= self.timeout_sec:
                logging.info("bridge timeout reached")
                self.close() # Close the bridge due a timeout
                break

            if not self.connections:
                # sleep if there is no connections
                time.sleep(self.delay)
                continue
            # blocks until there is socket(s) ready for .recv
            # notice: sockets which were closed by remote,
            #   are also regarded as read-ready by select()
            if self.selector:
                events = self.selector.select(self.timeout_sec)
                socks_rd = tuple(key.fileobj for key, mask in events if mask & EVENT_READ)
                socks_wr = tuple(key.fileobj for key, mask in events if mask & EVENT_WRITE)
            else:
                r, w, e = select.select(self.connections, self.connections, [], self.timeout_sec)
                socks_rd = tuple(r)
                socks_wr = tuple(w)
                # logging.debug('socks_rd: %s, socks_wr:%s', len(socks_rd), len(socks_wr))

            if not socks_rd and not socks_wr: # If select timeout reached (for both read and write ready sockets)
                logging.info("bridge timeout reached")
                self.close() # Close the bridge due a timeout

            if not socks_rd and not self.send_buff:  # reduce CPU in low traffic if there is no read-ready sockets
                time.sleep(self.delay)
                continue
            
            # logging.debug('got rd:%s wr:%s', socks_rd, socks_wr) 
            # ----------------- RECEIVING ----------------
            for s in socks_rd:  # type: socket.socket
                
                # if this socket has non-sent data, stop recving more, to prevent buff blowing up.
                if self.map[s] in self.send_buff:
                    # logging.debug('delay recv because another too slow %s', self.map.get(s))
                    continue

                try:
                    received = s.recv(RECV_BUFFER_SIZE)
                    self._last_success_read = datetime.datetime.now() # Reset timeout timer
                    # logging.debug('recved %s from %s', len(received), s)
                except Exception as e:
                    # unable to read, in most cases, it's due to socket close
                    logging.warning('error reading socket %s, %s closing', repr(e), s)
                    self._terminate(s)
                    continue

                if not received:
                    self._terminate(s)
                    continue
                else:
                    self.send_buff[self.map[s]] = received

            # ----------------- SENDING ----------------
            for s in socks_wr:
                if s not in self.send_buff:
                    continue
                data = self.send_buff.pop(s)
                try:
                    s.send(data)
                    # logging.debug('sent %s to %s', len(data), s)
                except Exception as e:
                    # unable to send, close connection
                    logging.warning('error sending socket %s, %s closing', repr(e), s)
                    print("eror write")
                    print(s)
                    self._terminate(s)
                    continue
    

    def close (self, from_outside = False):
        """close the SocketBridge
        """
        self.work = False
        
        for s in self.connections:
            try_close(s)  # close the first socket
            self.send_buff.pop(s, None)
            if self.selector:
                try:
                    self.selector.unregister(s)
                except:
                    pass
        
        self.map.clear()

        # ------ callback --------
        if not from_outside: # If bridge closed from outside - there is no use in callback
            if self.callback: 
                self.callback()

        
    def _terminate(self, conn, once=False):
        """terminate a sockets pair (two socket)
        :type conn: socket.socket
        :param conn: any one of the sockets pair
        """
        logging.debug('terminate %s',conn)
        try_close(conn)  # close the first socket

        # ------ close and clean the mapped socket, if exist ------
        _another_conn = self.map.pop(conn, None)

        if conn in self.connections:
            self.connections.remove(conn)

        self.send_buff.pop(conn, None)
        if self.selector:
            try:
                self.selector.unregister(conn)
            except:
                pass

        # terminate another
        if not once and _another_conn in self.map:
            self._terminate(_another_conn, True)