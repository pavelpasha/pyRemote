""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""
# Configuration area
TUNNEL_IDLE_TIMEOUT = 60 # seconds
ALIVE_PING_FREQUENCY = 60 # seconds. Send alive ping period

MASTER_HOST = "localhost"
MASTER_PORT = 444

DEVICE_NAME = "Test windows device"

SSL_ENABLED = False
#

import socket
import sys
import threading
import time
import os
import select
import serial
import ssl
from uuid import getnode as get_mac
""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""
import struct
import logging

class MessageType:
    HANDSHAKE = 0
    TUNNEL_REQUEST = 1
    CONNECTION_REQUEST = 2
    TUNNEL_CLOSED = 3

class Proto:
    TCP = 0
    SERIAL = 1


class ControlMessage ():
    """
        A base class of control messages to communicate between slaves and master.
        message = header (version: uint_8, message type: uint_8) + payload
    """
    #static fields
    header_format = "<BB"
    version = 1.0
    HEADER_SIZE = 2
    @classmethod
    def from_bytes (cls,payload):
        (version,message_type)  = struct.unpack(cls.get_header_format(),payload[:cls.HEADER_SIZE])
        #if version != cls.get_version():
            #logging.error("message protocol versions is not match: {} and {}".format(float(version)/10, cls.version))
        if message_type == MessageType.HANDSHAKE:
            return HandshakeMessage.from_bytes(payload[cls.HEADER_SIZE:])
        elif message_type == MessageType.TUNNEL_REQUEST:
            return TunnelReqMessage.from_bytes(payload[cls.HEADER_SIZE:])
        elif message_type == MessageType.CONNECTION_REQUEST:
            return ConnectionReqMessage.from_bytes(payload[cls.HEADER_SIZE:])
        elif message_type == MessageType.TUNNEL_CLOSED:
            return TunnelClosedMessage.from_bytes(payload[cls.HEADER_SIZE:])

        return None
    @staticmethod
    def get_header_format():
        return ControlMessage.header_format
    
    @staticmethod
    def get_version():
        return int(ControlMessage.version*10)

    @classmethod
    def _add_header(cls,message_type, payload):
        return struct.pack(cls.get_header_format(),cls.get_version(),message_type) + payload

class HandshakeMessage(ControlMessage):
    def __init__(self, hwId, name):
        self.hwId = hwId
        if (len(name) > 255):
            raise Exception ("Device name is too long")
        self.name = name

    @classmethod
    def from_bytes(cls, payload):
        try:
            (hwid,name_len) = struct.unpack("<QB",payload[0:9])
            return (cls(hwid,payload[-name_len:].decode()))
        except:
            return None

    def encode (self):
        payload = struct.pack(self._get_format(),self.hwId,len(self.name), self.name.encode())
        return self._add_header(MessageType.HANDSHAKE, payload)
    
    def _get_format(self):
        """
        hwId (uint_64), len_of name (uint_8), name (n*s)
        """
        return "<QB{}s".format(len(self.name)) 


class ConnectionReqMessage(ControlMessage):
    def __init__(self, tunnel_id):
        self.tunnel_id = tunnel_id

    @classmethod
    def from_bytes(cls, payload):
        try:
            (tunnel_id,) = struct.unpack("<H",payload)
            return (cls(tunnel_id))
        except:
            return None

    def encode (self):
        payload = struct.pack(self._get_format(),self.tunnel_id)
        return self._add_header(MessageType.CONNECTION_REQUEST, payload)
    
    def _get_format(self):
        """
        tunnel_id (uint_16)
        """
        return "<H"

class TunnelClosedMessage(ControlMessage):
    """ A tunnel closed callback message. 
    """
    def __init__(self, tunnel_id):
        self.tunnel_id = tunnel_id

    @classmethod
    def from_bytes(cls, payload):
        try:
            (tunnel_id,) = struct.unpack("<H",payload)
            return (cls(tunnel_id))
        except:
            return None

    def encode (self):
        payload = struct.pack(self._get_format(),self.tunnel_id)
        return self._add_header(MessageType.TUNNEL_CLOSED, payload)
    
    def _get_format(self):
        """
        tunnel_id (uint_16)
        """
        return "<H"

class TunnelReqMessage(ControlMessage):
    """ A new tunnel request message. 
    """
    def __init__(self, communicate_port, ssl = False, hostname = None, port = None, ser_name = None, baudrate = None):
        if hostname and port:
            self.proto = Proto.TCP
            self.hostname = hostname
            self.port = port
        elif ser_name and baudrate:
            self.proto = Proto.SERIAL
            self.ser_name = ser_name
            self.baudrate = baudrate
        else:
            raise Exception("Wrong parameters given")
        self.communicate_port = communicate_port
        self.ssl = ssl

    @classmethod
    def from_bytes(cls, payload):
        try:
            (communicate_port,proto, ssl) = struct.unpack("<HBB",payload[0:4])
            if proto == Proto.TCP:
                (port, host_len ) = struct.unpack("<HB",payload[4:7])
                return cls(communicate_port = communicate_port, ssl = ssl, hostname = payload[-host_len:].decode(),port = port)
            elif proto == Proto.SERIAL:
                (baudrate, ser_name_len ) = struct.unpack("<IB",payload[4:9])
                return cls(communicate_port = communicate_port, ssl = ssl, ser_name = payload[-ser_name_len:].decode(), baudrate= baudrate)
            return None
        except Exception as e:
            print(e)
            return None
             
    def encode (self):
        payload = None
        if self.proto == Proto.TCP:
            payload =  struct.pack(self._get_format(), self.communicate_port, 
            self.proto, self.ssl, self.port, len(self.hostname), self.hostname.encode() )
        else:
            payload =  struct.pack(self._get_format(), self.communicate_port, 
            self.proto, self.ssl, self.baudrate, len(self.ser_name), self.ser_name.encode())
        return self._add_header(MessageType.TUNNEL_REQUEST, payload)

    def _get_format(self):
        """
        communicate_port (uint_16), proto (uint_8), ssl(uint_8)
            -> port (uint_16), len_of hostname (uint_8), hostname (n*s)
            or
            -> baudrate (uint_32), len_of ser_name (uint_8), ser_name (n*s)
        """
        if self.proto == Proto.TCP:
            return "<HBBHB{}s".format(len(self.hostname)) 
        else:
            return "<HBBIB{}s".format(len(self.ser_name))
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
class AbstractTunnel:
    pass

class Serial_tunnel_client(AbstractTunnel):

    def __init__ (self,server_port, serial_name, serial_params, ssl, close_callback):
        self._work = True
        self._server_port = server_port
        self._serial_name = serial_name
        self._serial_params = serial_params
        self._ssl = ssl and SSL_ENABLED
        self._close_callback = close_callback
        self._ser = None
        self._serv_sock = None
        threading.Thread(target=self._run, name="serial_tunnel", args=[]).start()

    def _listen_serial (self):
        """ Windows specific
        """
        while self._work:
            try:
                # If inWaiting() returns 0, the read() function just will return 0 and resets a reading timeout,
                # so we need to wait at leas 1 byte in this case
                data = self._ser.read(self._ser.inWaiting() if self._ser.inWaiting() else 1)
                if data:
                    self._serv_sock.sendall(data)
            except:
                self._terminate()
    

    def _listen_tcp (self):
        """Windows specific
        """
        while self._work:
            try:
                data = self._serv_sock.recv(256)
                if data:
                    self._ser.write(data)
                else:
                    raise Exception ("Connection broken")
            except Exception as e:
                self._terminate()


    def _run (self):
        try:

            self._ser = serial.Serial(self._serial_name, self._serial_params, timeout=TUNNEL_IDLE_TIMEOUT)
            if self._ssl:
                self._serv_sock = ssl.wrap_socket(socket.socket(), ssl_version=ssl.PROTOCOL_SSLv23)
            else:
                self._serv_sock = socket.socket()

            self._serv_sock.connect((MASTER_HOST, self._server_port))

            if sys.platform != 'win32': # Unix
                while self._work:
                    self._ser.timeout = 0
                    self._serv_sock.setblocking(0)
                    connections = [self._ser, self._serv_sock]
                    read, write, err = select.select(connections,connections,connections,TUNNEL_IDLE_TIMEOUT)

                    for r in read:
                        if r == ser:
                            data = self._ser.read(self._ser.inWaiting())
                            self._serv_sock.sendall(data)
                        else:
                            data = self._serv_sock.recv(512)
                            if data:
                                self._ser.write(data)
                            else:
                                raise Exception ("Connection broken")
            
            else: # If windows. On which Serial has no fileno() method and can`t work with select
                threading.Thread(target=self._listen_serial, name="listen_serial", args=[]).start()
                threading.Thread(target=self._listen_tcp, name="listen_tcp", args=[]).start()

                while self._work:
                    time.sleep(1)

        except Exception as e:
            print (e)
            self._terminate()  

    def _stop(self):
        self._work = False
        try_close(self._ser)
        try_close(self._serv_sock)

    def _terminate (self):
        logging.debug("Tunnel closed from inside")
        self._stop()
        self._close_callback(self._server_port)
    
    def close(self):
        """ Close the tunnel forcibly from outside
        """
        logging.debug("Tunnel closed forcibly")
        self._stop()

class TCP_tunnel_client(AbstractTunnel):

    def __init__ (self,server_port, tunnel_host, tunnel_port, ssl, close_callback):
        self._work = True
        self._server_port = server_port
        self._tunnel_port = tunnel_port
        self._tunnel_host = tunnel_host
        self._ssl = ssl and SSL_ENABLED
        self._close_callback = close_callback
        self._socket_bridge = SocketBridge(self._terminate,TUNNEL_IDLE_TIMEOUT)
        threading.Thread(target=self._run, name="tcp_tunnel", args=[]).start()

    def _run (self):
        try:
            self._socket_bridge.start_as_daemon() 

            forw_sock = socket.socket()
            forw_sock.connect((self._tunnel_host, self._tunnel_port))

            if self._ssl:
                serv_sock = ssl.wrap_socket(socket.socket(), ssl_version=ssl.PROTOCOL_SSLv23)
            else:
                serv_sock = socket.socket()

            serv_sock.connect((MASTER_HOST, self._server_port))
            
            self._socket_bridge.add_pair(
                serv_sock, forw_sock       
            )
            while self._work:
                time.sleep(5)

        except Exception as e:
            self._work = False
            print (e)
    
    def connect (self):
        try:     
            forw_sock = socket.socket()
            forw_sock.connect((self._tunnel_host, self._tunnel_port))

            if self._ssl:
                serv_sock = ssl.wrap_socket(socket.socket(), ssl_version=ssl.PROTOCOL_SSLv23)
            else:
                serv_sock = socket.socket()
            serv_sock.connect((MASTER_HOST, self._server_port))

            self._socket_bridge.add_pair(
                serv_sock, forw_sock       
            )
        except Exception as e:
            print (e)

    def _terminate (self):
        logging.debug("Tunnel closed from inside")
        self._work = False
        self._close_callback(self._server_port)
    
    def close(self):
        """ Close the tunnel forcibly from outside
        """
        logging.debug("Tunnel closed forcibly")
        self._work = False
        self._socket_bridge.close(True)



class Slaver ():

    def __init__ (self, server_host, server_port, device_name):
        self.server_host = server_host
        self.server_port = server_port
        self.server_socket = None
        self.hwId = self.get_hwid()
        self.name = device_name
        self.opened_tunnels = {}
        self._connect()
        threading.Thread(target = self._send_alive_ping, args = []).start()
        self._listen_to_server()
        

    @staticmethod
    def get_hwid(): 
        """
        rtype: int
        """
        return get_mac()

    def _create_handshake (self):
        """
        rtype: bytes
        """ 
        return HandshakeMessage(self.get_hwid(),self.name).encode()

    def _listen_to_server (self):
        while True:
            try:
                data = self.server_socket.recv(256)
                if data:
                    self._handle_message(ControlMessage.from_bytes(data))                
            except Exception as e:
                logging.error("Error while reading data from command socket: {}".format(e))
                self.server_socket.close()
                self._connect()

    def _connect(self):
        connected = False
        while not connected:
            try:
                if SSL_ENABLED:
                    self.server_socket = ssl.wrap_socket(socket.socket(), ssl_version=ssl.PROTOCOL_SSLv23)
                else:
                    self.server_socket = socket.socket()
                self.server_socket.connect((self.server_host, self.server_port))
                self.server_socket.sendall(self._create_handshake())
                connected = True
            except Exception as e:
                logging.error("Error while connectiong to command socket: {}".format(e))
                self.server_socket.close()
                time.sleep(5)


    def _send_to_server(self, command):
        """
            type command: string or ControlMessage
        """
        try:
            self.server_socket.sendall(command.encode())
        except Exception as e:
            logging.error("Error while sending command to command socket: {}".format(e))
            self.server_socket.close()

    def _send_alive_ping(self):
        while True:
            time.sleep(5)
            self._send_to_server("0\n")
        
    def _handle_message(self,message):
        """ Handle message from server command socket
            type message: ControlMessage
        """
        print("new message")
        if None == message:
            return

        if isinstance(message,TunnelReqMessage):
            server_port = message.communicate_port
            if message.proto == Proto.TCP:
                self.opened_tunnels[server_port] = TCP_tunnel_client(server_port, message.hostname, message.port, message.ssl, self._on_tunnel_closed)
            else:
                self.opened_tunnels[server_port] = Serial_tunnel_client(server_port, message.ser_name, message.baudrate, message.ssl, self._on_tunnel_closed)
        elif isinstance(message, ConnectionReqMessage):
            tunnel_id = message.tunnel_id
            if tunnel_id in self.opened_tunnels:
                logging.debug("Another connection requested for tunnel {}".format(tunnel_id))
                self.opened_tunnels[tunnel_id].connect()
        elif isinstance(message,TunnelClosedMessage):
            tunnel_id = message.tunnel_id
            if tunnel_id in self.opened_tunnels:
                logging.debug("Server asked to close the tunnel {}".format(tunnel_id))
                tunnel = self.opened_tunnels.pop(tunnel_id, None)
                if None != tunnel:
                    tunnel.close()
    
    def _on_tunnel_closed (self, tunnel_id):
        self.opened_tunnels.pop(tunnel_id, None)
        # Let server know that this tunnel is closed 
        self._send_to_server(TunnelClosedMessage(tunnel_id))
        
        

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    host = Slaver(MASTER_HOST, MASTER_PORT,DEVICE_NAME)
    
    

        
    