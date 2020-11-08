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