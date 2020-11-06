""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""
import socket
import datetime
import threading
import time
import json
import select
import random
import errno
import sys
from database import database
import config
import ssl
from common.control_message import *
from common.socket_bridge import *

# A tunnel status codes
ERROR = -1
STARTED = 0
OPENED = 1
READY = 2
WAITING = 3
#

PORTS_RANGE = [3000, 4000] # Range of allowed ports

ONLINE = 1
OFFLINE = 0

PY3_OR_LATER = sys.version_info[0] >= 3
SSL_ENABLED = False

# < Utillits >
def get_random_port():
    return random.randrange(PORTS_RANGE[0], PORTS_RANGE[1], 1)


def bind_unused_port(sock):
    # Lets find an unused port and bind it to given socket
    port = get_random_port()
    attempts_left = 100
    while True:
        try:
            server_address = ('0.0.0.0', port)
            sock.bind(server_address)
            break
        except socket.error as e:
            if e.errno == errno.EADDRINUSE:  # if port is used -> try another
                port = get_random_port()
                attempts_left -= 1
                if attempts_left < 1:
                    return None
            else:
                return None
    return port
# </ Utillits >


class TCP_tunnel_server():

    def __init__(self, slaver, options, close_callback):

        self._status = STARTED  # Holds a status code (online or not)
        self._slaver = slaver
        self._work = True
        self._options = options
        self._socket_bridge = SocketBridge(self._terminate)
        self._customer_socket = None
        self._communicate_socket = None
        self._close_callback = close_callback
        self._ssl = options["ssl"] and SSL_ENABLED

    def start(self):
        threading.Thread(target=self._run, args=[], name="tunnel").start()

    def _run(self):
        try:
            if self._ssl:
                self._communicate_socket = ssl.wrap_socket(socket.socket(), 'ssl/server.key', 'ssl/server.crt',
                ssl_version=ssl.PROTOCOL_SSLv23, server_side = True)
            else:
                self._communicate_socket = socket.socket()

            self.communicate_port = bind_unused_port(self._communicate_socket)
            print(self.communicate_port)
            if not self.communicate_port:
                return

            self.set_status(OPENED)

            try:
                message = None
                proto = self._options["proto"]

                if proto == "tcp":
                   message = TunnelReqMessage(communicate_port = self.communicate_port, ssl = self._ssl,
                   hostname = str(self._options["host"]), port = int(self._options['port']))
                else:
                    message = TunnelReqMessage(communicate_port = self.communicate_port, ssl = self._ssl,
                    ser_name = str(self._options["ser_name"]), baudrate = int(self._options['rate']))

                self._slaver.socket.sendall(message.encode())

            except:
                self.set_status(ERROR)
                return

            self._communicate_socket.listen(1)
            # 15 sec for waiting remote device to connect, or tunnel will be closed by reason of timeout
            self._communicate_socket.settimeout(15)

            slaver_conn, _ = self._communicate_socket.accept()
            # Remote device connected to the server, and it client`s time to connect

            self._customer_socket = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM)
            self.customer_port = bind_unused_port(self._customer_socket)
            if not self._customer_socket:
                self.set_status(ERROR)
                return

            self.set_status(READY)
            #self._slaver.status = self.customer_port

            self._customer_socket.listen(1)
            # 60 sec for waiting customer to connect, or tunnel will be closed by reason of timeout
            self._customer_socket.settimeout(60)

            customer_conn, _ = self._customer_socket.accept()

            self._socket_bridge.start_as_daemon()

            self._socket_bridge.add_pair(
                customer_conn, slaver_conn
            )

            threading.Thread(target=self._listen_for_customers,
                             args=[], name="customer listen").start()

            while self._work:
                time.sleep(5)
        except Exception as e:
            self._status = ERROR
            self._terminate()

    def _listen_for_customers(self):
        """ Non - blocking customers accept routine 
            It accepts new a customers and requests a new connection from slaver
            Then adds both conections to the socket bridge
        """
        while self._work:
            readable, _, _ = select.select([self._customer_socket], [], [], 5)
            if readable:
                try:
                    customer_conn, _ = self._customer_socket.accept()  # New customer accepted
                except:
                    continue
                try:
                    # Say to slaver, that we need one more connection
                    self._slaver.socket.sendall(ConnectionReqMessage(self.communicate_port).encode())
                except:
                    break
            else:
                continue
            # 5 sec for waiting remote device to connect, or tunnel will be closed by reason of timeout
            self._communicate_socket.settimeout(5)

            slaver_conn, _ = self._communicate_socket.accept()
            # As we now have two new connections (from customer and slaver), lets add it to bridge
            self._socket_bridge.add_pair(
                customer_conn, slaver_conn
            )
    

    def _stop (self):
        self._work = False
        try_close(self._communicate_socket)
        try_close(self._customer_socket)
        # Assuming that slaver have been online when tunnel was started. So lets restore this status again
        if self._slaver.status != OFFLINE:
            self._slaver.status = ONLINE

    def _terminate(self):
        """ Close the tunnel from inside. Due an error or timeout
        """
        logging.debug("Tunnel terminated")
        self._stop()
        # Let server know that the tunnel is closed, so it can delete if from opened tunnels list
        # Communicate port uses as tunnel ID (because it unique and both: server and slaver knows it)
        self._close_callback(self.communicate_port)

    def close(self):
        """ Close the tunnel forcibly from outside
        """
        logging.debug("Tunnel closed forcibly")
        self._stop()
        # A "True" parameter - says to SocketBridge that it closed forcibly and not need to fire "on closed" callback
        self._socket_bridge.close(True) 
        
    def get_status(self):
        return self._status

    def set_status(self, status):
        self._status = status

    def get_customer_port(self):
        return self.customer_port

    def get_communicate_port(self):
        return self.communicate_port
    
    def get_options(self):
        return self._options

    def get_slaver(self):
        return self._slaver

    


class Slaver ():
    def __init__(self, socket, hwId, name):
        """ type socket: socket.socket()
            type hwId: int
            type name: string
        """
        self.socket = socket
        self.hwId = hwId
        self.last_update = time.time()
        self.name = name
        self.status = OFFLINE # {0: offline, 1: online; from 2 to 65535 : a port number of already opened tunnel}

    def serialize(self):
        if PY3_OR_LATER:
            return dict((k, v) for (k, v) in self.__dict__.items() if v != self.socket)
        else:
            return dict((k, v) for (k, v) in self.__dict__.iteritems() if v != self.socket)


class RemoteServer ():
    def __init__(self, port):
        self._port = port
        self._slavers = {}
        self._load_known_slavers()
        self._opened_tunnels = {}
        threading.Thread(target=self._run, args=[]).start()

    def _load_known_slavers(self):
        """ Loading a list of known slavers from database at application start
        """
        clients = database.get_slavers_list()
        if clients:
            for client in clients:
                self._slavers[client.hwId] = client

    def _run(self):
        """ The main loop. It accepts a new slaver connections,
            asks it for its name and id, then if all ok - appends it to the list
            and creates a new thread for each connection.
        """
        if SSL_ENABLED:
            sock = ssl.wrap_socket(socket.socket(),  'ssl/server.key', 'ssl/server.crt', server_side = True)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        server_address = ('0.0.0.0', self._port)
        sock.bind(server_address)
        sock.listen(1)
        slaver_socket = None
        while True:
            try:
                slaver_socket, _ = sock.accept()
                logging.debug("new connection {}".format(slaver_socket.getsockname()))
                
                threading.Thread(target=self._handle_slaver,
                                    args=[slaver_socket]).start()
            except ssl.SSLError:
                logging.error("Slaver connection SSL error")
            except:
                pass



    def _handle_slaver(self, connection):
        """ Listen what slaver will say. 
            Runs in dedicated thread for each active slaver connection
            type slaver: Slaver ()
        """
        try:
            connection.settimeout(5)  # Wait 5 sec for handshake
            hs = ControlMessage.from_bytes(connection.recv(128))
            if (None ==  hs and not isinstance(hs,HandshakeMessage)):
                return
            slaver = Slaver(connection, hs.hwId, hs.name)
            slaver.status = ONLINE # Mark it as online
            database.log(slaver.hwId, slaver.status, time.time()) # Wite log to database: slaver ID and connection time
            database.write(slaver) # Add to base of know slavers. Or update, if slaver with such it already exists
            self._slavers[hs.hwId] = slaver # Add it to list of slavers
            logging.debug("new slaver connected: {}".format(slaver.name))
        except:
            try_close(connection)
            return

        slaver.socket.settimeout(config.HOST_ALIVE_TIMEOUT)
        while True:
            try:
                data = slaver.socket.recv(256)
                if not data:
                    raise Exception("Connection broken")

                slaver.last_update = time.time()
                database.write(slaver)
                if len(data) > 2:  # If not just alive ping
                    message = ControlMessage.from_bytes(data)
                    self._process_message(message)

            except Exception as e:
                logging.debug("Exception occures while listening to slaver socket: {}".format(e))
                try_close(slaver.socket)
                slaver.status = OFFLINE
                database.log(slaver.hwId, slaver.status, time.time())
                break  # Exit from the loop and shutdown the thread

    def _process_message(self, message):
        """
        type message: ControlMessage
        """
        if None == message:
            return

        if isinstance(message, TunnelClosedMessage): 
            """ Message when tunnel with given id has closed by slaver.
                So we need to close it on the server side too.
            """ 
            try:
                tunnel = self._opened_tunnels.pop(message.tunnel_id, None)
                if None != tunnel:
                    tunnel.close()
            except:
                pass
    
    def _on_tunnel_closed (self, tunnel_id):
        """ Callback when tunnel with given id has closed by server.
            So we need to remove it from list of opened tunnels
            type tunnel_id: int
        """
        self._opened_tunnels.pop(tunnel_id, None)


    def get_slavers_list(self):
        """
            Returns a list of slavers (both online and offline) via json string
            rtype: String
        """
        return json.dumps([json.dumps(self._slavers[key].serialize()) for key in self._slavers])

    def open_tunnel(self, options):
        id = int(options["id"])
        # If there is no client with such ID or the client exists but it is offline -> return error
        if id not in self._slavers or self._slavers[id].status == OFFLINE:
            return "ERROR Client not found or offline"

        # First lets check if a tunnel with a requested options already opened
        for _, tunnel in self._opened_tunnels.iteritems():
            if tunnel.get_options() == options: # If does -> just return a coonection parameters
                logging.debug("Requested tunnel already opened")
                return '{{"status": "ok", "port": {0},"id": {1} }}'.format(str(tunnel.get_customer_port()),str(tunnel.get_communicate_port()))

        tunnel = TCP_tunnel_server(self._slavers[id], options, self._on_tunnel_closed)
        tunnel.start()
        while True:
            time.sleep(0.5)
            status = tunnel.get_status()
            if status == READY:
                # Tunnel`s communicate port uses also as its ID
                self._opened_tunnels[tunnel.get_communicate_port()] = tunnel
                return '{{"status": "ok", "port": {0},"id": {1} }}'.format(str(tunnel.get_customer_port()),str(tunnel.get_communicate_port()))
            elif status == ERROR:
                return '{"status": "error"}'

    def close_tunnel (self, tunnel_id):
        tunnel = self._opened_tunnels.pop(tunnel_id, None)
        if None != tunnel:
            try:
                tunnel.get_slaver().socket.sendall(TunnelClosedMessage(tunnel_id).encode())
            except:
                pass
            tunnel.close()
        return '{"status": "success"}'

    def get_slaver_status(self, id):
        """ Returns a status of the certaint host: online or offline
            type id: int
            rtype: json string
        """
        if id not in self._slavers:
            return '{"status":-1}'
        return str(self._slavers[id].status)

    def get_slaver_name (self, hwId):
        slaver = self._slavers.get(hwId, None)
        return slaver.name if slaver else ""
    
    def remove_slaver (self, hwId):
        self._slavers.pop(hwId, None)
        return database.delete_slaver(hwId)

if __name__ == "__main__":
    rem_server = RemoteServer(555)
