import os

output_name = "bundle.py"

source =  open ("slaver.py")
out = open(output_name, "w")
    
content = source.readlines()
for line in content:
    if "from socket_bridge" in line:
        f = open ("socket_bridge.py")
        out.write(f.read())
        f.close()
    elif "common.control_message" in line:
        f = open ("../common/control_message.py")
        out.write(f.read())
        f.close()
    else:
        out.write(line)

source.close()
out.close()


# Now lets remove dublicating imports
out = open(output_name,"r")
content = out.readlines()
out.close()
out = open(output_name,"w")
imports = []
for line in content:
    if line.startswith("import"):
        if line not in imports:
            out.write(line)
            imports.append(line)
    else:
        out.write(line)
out.close()