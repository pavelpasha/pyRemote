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
import ssl
from socket_bridge import *
from ..common.control_message import *

class AbstractTunnel:
    pass

class SSLSocket():
    def __init__(self, socket, fileno):
        self.socket = socket
        self.fileno = fileno
    
    def fileno (self):
        return self.fileno
    
    def recv (self, size):
        self.socket.read(size)
    
    def send (self, bytes):
        self.socket.write(bytes)
      

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
                #self.server_socket = socket.socket()
                self.server_socket = ssl.wrap_socket(socket.socket(), ssl_version=ssl.PROTOCOL_SSLv23)
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

        
    