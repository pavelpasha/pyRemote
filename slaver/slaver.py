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
from ..common.control_message import *
from ..common.socket_bridge import *

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
    
    

        
    