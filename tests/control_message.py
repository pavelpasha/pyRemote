from ..common.control_message import *

if __name__ == "__main__":
    ser_name = "com21"
    baudrate = 321
    com_port = 666
    data = TunnelReqMessage(communicate_port=com_port, ser_name=ser_name, baudrate= baudrate).encode()
    ms = ControlMessage.from_bytes(data)
    assert ms.ser_name == ser_name, "tunnel request message error"
    assert ms.baudrate == baudrate, "tunnel request message error"
    assert ms.communicate_port == com_port, "tunnel request message error"

    hostname = "localhost"
    port = 65535
    data = TunnelReqMessage(communicate_port=com_port, hostname=hostname, port= port).encode()
    ms = ControlMessage.from_bytes(data)
    assert ms.hostname == hostname, "tunnel request message error"
    assert ms.port == port, "tunnel request message error"
    assert ms.communicate_port == com_port, "tunnel request message error"

    hwid = 1235
    name = "test device"
    data = HandshakeMessage(hwid, name).encode()
    ms = ControlMessage.from_bytes(data)
    assert ms.hwId == hwid, "handshake message error"
    assert ms.name == name, "handshake message error"

    tunnel_id = 12345
    data = TunnelClosedMessage(tunnel_id).encode()
    ms = ControlMessage.from_bytes(data)
    assert ms.tunnel_id == tunnel_id, "tunnel closed message error"


    data = ConnectionReqMessage(tunnel_id).encode()
    ms = ControlMessage.from_bytes(data)
    assert ms.tunnel_id == tunnel_id, "connection request message error"
