""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""
# Configuration area
TUNNEL_IDLE_TIMEOUT_SEC = 60 # seconds
ALIVE_PING_FREQUENCY = 60 

SERVER_HOST = "192.168.1.229"
SERVER_PORT = 444

DEVICE_NAME = "Test openwrt device"
#


import socket
import threading
import time
import os
import select
import logging
import serial
import uselect
#!/usr/bin/env python
# coding=utf-8

""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""

import collections
import traceback

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

""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""
import struct

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




class AbstractTunnel:
    pass

class Serial_tunnel_client(AbstractTunnel):

    def __init__ (self,server_port, serial_name, serial_params, close_callback):
        self._work = True
        self._server_port = server_port
        self._serial_name = serial_name
        self._serial_params = serial_params
        self._poller = uselect.poll()
        self._close_callback = close_callback
        self._ser = None
        self._serv_sock = None
        threading.Thread(target=self._run, name="tunnel", args=[]).start()


    def _run (self):
        try:

            self._ser = serial.Serial(self._serial_name, self._serial_params, timeout=TUNNEL_IDLE_TIMEOUT_SEC)
        
            self._serv_sock = socket.socket()
            self._serv_sock.connect((SERVER_HOST, self._server_port))

            self._poller.register(self._ser.fileno(), uselect.POLLIN | uselect.POLLHUP)
            self._poller.register(self._serv_sock.fileno(), uselect.POLLIN | uselect.POLLHUP)

            while self._work:
                self._serv_sock.setblocking(0)
                connections = [self._ser, self._serv_sock]
                events = self._poller.poll(TUNNEL_IDLE_TIMEOUT_SEC*1000)
                if not events: # Timeout
                    self._terminate()
                    break
                read = tuple(key for key, mask in events if mask & uselect.POLLIN)

                for r in read:
                    if r == self._ser.fileno():
                        data = self._ser.read(self._ser.inWaiting())
                        self._serv_sock.sendall(data)
                    else:
                        data = self._serv_sock.recv(512)
                        if data:
                            self._ser.write(data)
                        else:
                            raise Exception ("Connection broken")
            
           
        except Exception as e:
            print (e)
            self._terminate()

    def _stop(self):
        self._work = False
        try_close(self._ser)
        try_close(self._serv_sock)

    def _terminate (self):
        print("tunnel closed")
        self._stop()
        self._close_callback(self._server_port)
    
    def close(self):
        """ Close the tunnel forcibly from outside
        """
        logging.debug("Tunnel closed forcibly")
        self._stop()

class TCP_tunnel_client(AbstractTunnel):

    def __init__ (self,server_port, tunnel_host, tunnel_port, close_callback):
        self._work = True
        self.server_port = server_port
        self.tunnel_port = tunnel_port
        self.tunnel_host = tunnel_host
        self.socket_bridge = SocketBridge(self._terminate,TUNNEL_IDLE_TIMEOUT_SEC)
        self._close_callback = close_callback
        threading.Thread(target=self._run, name="tunnel", args=[]).start()

    def _run (self):
        try:
            self.socket_bridge.start_as_daemon() 

            forw_sock = socket.socket()
            forw_sock.connect((self.tunnel_host, self.tunnel_port))

            serv_sock = socket.socket()
            serv_sock.connect((SERVER_HOST, self.server_port))
            
            self.socket_bridge.add_pair(
                serv_sock, forw_sock       
            )
            while self._work:
                time.sleep(5)

        except Exception as e:
            self.work = False
            logging.info("Error while established a first connection to tunnel %s", e)
    
    def connect (self):
        try:     
            forw_sock = socket.socket()
            forw_sock.connect((self.tunnel_host, self.tunnel_port))

            serv_sock = socket.socket()
            serv_sock.connect((SERVER_HOST, self.server_port))

            self.socket_bridge.add_pair(
                serv_sock, forw_sock       
            )
        except Exception as e:
            logging.info("Error while established a new connection to tunnel %s", e)

    def _terminate (self):
        print("tunnel closed")
        self._work = False
        self._close_callback(self.server_port)
    
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
        self.poller = select.epoll()
        self._connect()
        threading.Thread(target = self._send_alive_ping, args = []).start()
        self._listen_to_server()
        

    @staticmethod
    def get_hwid():
        cmd_out = os.popen("ifconfig| grep HWaddr |cut -dH -f2|cut -d\  -f2").read() # get mac addresss of all interfaces 
        mac_adr_str = cmd_out.split('\n', 1)[0].replace(":","") # get first of it
        return int ("0x"+mac_adr_str,0) #get_mac()  How to get mac address on micropython (Openwrt port)? I dont know 

    def _create_handshake (self):
        """
            rtype: bytes
        """
        return HandshakeMessage(self.hwId,self.name).encode()

    def _listen_to_server (self):
        """ Listening for maser server command socket
        """
        while True:
            self.server_socket.setblocking(0)
            
            while True:
                events = self.poller.poll()   
                error = False
                for fileno, event in events:
                    if event == select.EPOLLIN:
                        try:
                            data = self.server_socket.recv(256)
                            if data:
                                self._parse_command(ControlMessage.from_bytes(data))
                            else:
                                raise Exception ("Connection broken")
                        except Exception as e:
                            logging.info("Error while reading from master command socket %s", e)
                            error = True

                    elif event == select.EPOLLERR:
                        error = True

                if error:
                    self._reconnect_to_master()
                    

    def _connect(self):
        """ Connect to maser server command socket
        """
        connected = False
        while not connected:
            try:
                self.server_socket = socket.socket()
                self.server_socket.connect((self.server_host, self.server_port))
                self.server_socket.sendall(self._create_handshake())
                connected = True
                self.poller.register(self.server_socket.fileno(), select.EPOLLIN | select.EPOLLERR)
            except Exception as e:
                logging.info("Can`t connect to master command socket %s", e)
                self.server_socket.close()
                time.sleep(5)

    def _reconnect_to_master (self):
        self.poller.unregister(self.server_socket.fileno())
        try_close (self.server_socket)
        self._connect()

    def _send_to_master (self, data):
        try:
            self.server_socket.send(data.encode())
        except:
            self._reconnect_to_master()

    def _send_alive_ping(self):
        while True:
            time.sleep(5)
            self._send_to_master("0\n")
   
            
    def _parse_command(self,message):
        """ Parse command from server command socket
        :type command: ControlMessage
        """
        logging.debug("command received %s", message.__dict__)
        if isinstance(message, TunnelReqMessage):
            server_port = message.communicate_port
            if message.proto == 0:
                self.opened_tunnels[server_port] = TCP_tunnel_client(server_port, message.hostname, message.port, self._on_tunnel_closed)
            else:
                self.opened_tunnels[server_port] = Serial_tunnel_client(server_port, message.ser_name, message.baudrate, self._on_tunnel_closed)
        elif isinstance(message, ConnectionReqMessage):
            tunnel_id = message.tunnel_id
            if tunnel_id in self.opened_tunnels:
                logging.debug("another connection requested for tunnel %s", tunnel_id)
                self.opened_tunnels[int(tunnel_id)].connect()

    def _on_tunnel_closed (self, tunnel_id):
        self.opened_tunnels.pop(tunnel_id, None)
        # Let server know that this tunnel is closed
        self._send_to_master(TunnelClosedMessage(tunnel_id))

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    host = Slaver(SERVER_HOST, SERVER_PORT,DEVICE_NAME)

        
    