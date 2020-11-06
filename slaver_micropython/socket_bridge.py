#!/usr/bin/env python
# coding=utf-8

""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""

import collections
import logging
import socket
import threading
import time
import traceback
import select

# just a logger
#logging = logging.getLogger(__name__)


EVENT_READ_WRITE = select.EPOLLIN | select.EPOLLOUT
# socket recv buffer, 16384 bytes
RECV_BUFFER_SIZE = 2 ** 14

def try_close(connection):
    try:
        connection.close()
    except:
        pass


class SocketBridge ():

    def __init__ (self, terminate_callback = None, timeout = 60):
        self.work = True
        self.connections = set()  # holds all the sockets
        self.map = {}  # holds sockets pairs
        self.callback =  terminate_callback # holds callback
        self.send_buff = {}  # buff one packet for those sending too-fast socket
        self.timeout = timeout
        self.timeout_counter = 0
        self.delay = 0.1

        self.get_sock_by_fid = {}
        self.selector = select.epoll() # Create instance of selector
        

    def add_pair (self, conn1, conn2):
        """
        transfer anything between two sockets
        :type conn1: socket.socket
        :type conn2: socket.socket
        :param callback: callback in connection finish
        :type callback: Callable
        """
        # change to non-blocking
        #   we use select or epoll to notice when data is ready
        conn1.setblocking(False)
        conn2.setblocking(False)

        # mark as readable+writable
        self.connections.add(conn1)
        self.connections.add(conn2)

        # record sockets pairs
        self.map[conn1] = conn2
        self.map[conn2] = conn1

        # File descriptor to socket object map
        self.get_sock_by_fid[conn1.fileno()] = conn1
        self.get_sock_by_fid[conn2.fileno()] = conn2
            

        self.selector.register(conn1.fileno(), EVENT_READ_WRITE)
        self.selector.register(conn2.fileno(), EVENT_READ_WRITE)

        logging.debug("New pair added. total {}".format(len(self.connections)))


    def start_as_daemon(self):
        t = threading.Thread(target=self.start, name="socketBridge")
        t.daemon = True
        t.start()
        logging.debug("SocketBridge daemon started")
        return t

    def start(self):
        while self.work:
            try:
                self._start()
            except:
                logging.info("FATAL ERROR! SocketBridge failed {}".format(
                    traceback.format_exc()
                ))

    def _timeout_tick(self):
        self.timeout_counter += 1    # Increment the  timeout counter
        if self.timeout_counter * self.delay >= self.timeout: # Check if timeout reached
            logging.debug("bridge timeout reached")
            self._close() # Is so -> close the bridge

    def _start(self):  
        while self.work:
            if not self.connections:
                # sleep if there is no connections
                time.sleep(self.delay)
                self._timeout_tick()
                continue
            # blocks until there is socket(s) ready for .recv
            # notice: sockets which were closed by remote,
            #   are also regarded as read-ready by select()
            
            events = self.selector.poll(self.timeout)
            socks_rd = tuple(key for key, mask in events if mask & select.EPOLLIN)
            socks_wr = tuple(key for key, mask in events if mask & select.EPOLLOUT)
        
            # logging.debug('socks_rd: %s, socks_wr:%s', len(socks_rd), len(socks_wr))

            if not socks_rd and not socks_wr: # If select timeout reached (for both read and write ready sockets)
                logging.debug("bridge timeout reached")
                self._close() # Close the bridge due a timeout

            if not socks_rd and not self.send_buff:  # reduce CPU in low traffic if there is no read-ready sockets
                time.sleep(self.delay)
                self._timeout_tick()
            
            # logging.debug('got rd:%s wr:%s', socks_rd, socks_wr) 
            # ----------------- RECEIVING ----------------
            for s in socks_rd:  # type: socket.socket
                s = self.get_sock_by_fid[s]
                self.timeout_counter = 0
                # if this socket has non-sent data, stop recving more, to prevent buff blowing up.
                if self.map[s] in self.send_buff:
                    # logging.debug('delay recv because another too slow %s', self.map.get(s))
                    continue

                try:
                    received = s.recv(RECV_BUFFER_SIZE)
                    # logging.debug('recved %s from %s', len(received), s)
                except Exception as e:
                    # unable to read, in most cases, it's due to socket close
                    logging.debug('error reading socket %s, %s closing', repr(e), s)
                    self._terminate(s)
                    continue

                if not received:
                    logging.debug('error rd not received')
                    self._terminate(s)
                    continue
                else:
                    self.send_buff[self.map[s]] = received

            # ----------------- SENDING ----------------
            for s in socks_wr:
                s = self.get_sock_by_fid.get(s,None)
                if not s:
                    continue
                
                if s not in self.send_buff:
                    if self.map.get(s) not in self.connections:
                        self._terminate(s)
                    continue
                data = self.send_buff.pop(s)
                try:
                    s.send(data)
                    # logging.debug('sent %s to %s', len(data), s)
                except Exception as e:
                    # unable to send, close connection
                    logging.debug('error sending socket %s, %s closing', repr(e), s)
                    self._terminate(s)
                    continue

       

    def _close (self, from_outside = False):
        """close the SocketBridge
        """
        self.work = False
        
        for s in self.connections:
            try_close(s)  
            self.send_buff.pop(s, None)
            if self.selector:
                try:
                    self.selector.unregister(s.fileno())
                except:
                    pass

        # ------ callback --------
        if not from_outside: # If bridge closed from outside - there is no use in callback
            if self.callback: 
                self.callback()
        

    def _terminate(self, conn, once=False):
        """terminate and delete a socket
        :type conn: socket.socket
        :param conn: any one of the sockets pair
        """
        logging.debug('terminate %s',conn)
        try_close(conn)  # close the first socket

        # ------ close and clean the mapped socket, if exist ------
        _another_conn = self.map.pop(conn, None)
        try_close(_another_conn)  # close the second socket
        try:
            self.connections.remove(conn)
         
        except:
                pass
        
        self.send_buff.pop(conn, None)
        self.get_sock_by_fid.pop(conn.fileno(), None)
        if self.selector:
            try:
                self.selector.unregister(conn.fileno())
            except:
                pass
        # terminate another
        if not once and _another_conn in self.map:
            self._terminate(_another_conn, True)

    def _sel_disable_event(self, conn, ev):
        self.selector.unregister(conn.fileno())

