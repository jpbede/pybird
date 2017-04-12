#!/usr/bin/env python

from pybird import PyBird

pybird = PyBird(socket_file='/var/run/bird/bird.ctl')

peers = pybird.get_peer_status()
lineiterator = iter(peers)

first = True

print("{\n")
print("\t\"data\":[\n\n")

for peer in lineiterator:
    
    if "description" in peer:
       if first:
          print("\t{\n")
       else:
	  print("\t,{\n")

       print "\t\t\"{#PEERNAME}\":\"%s\",\n" % peer["description"]
       print "\t\t\"{#PROTONAME}\":\"%s\"\n" % peer["name"]
       print("\t}\n")
       first = False

print("\n\t]\n")
print("}\n")
