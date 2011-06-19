# Copyright (c) 2011, Erik Romijn <eromijn@solidlinks.nl>
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <organization> nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS

import re
import socket
from datetime import datetime, timedelta, date

class PyBird(object):
    ignored_field_numbers = [0001, 2002, 0000]
    
    def __init__(self, socket_file):
        self.socket_file = socket_file
        self.clean_input_re = re.compile('\W+')
        self.field_number_re = re.compile('^(\d+)[ -]')
        self.routes_field_re = re.compile('(\d+) imported, (\d+) exported')


    def get_peer_status(self, peer_name=None):
        if peer_name:
            query = 'show protocols all "%s"' % self._clean_input(peer_name)
        else:
            query = 'show protocols all'
            
        data = self._send_query(query)
        peers = self._parse_peer_data(data=data, data_contains_detail=True)
        
        if not peer_name:
            return peers
            
        if len(peers) != 1:
            raise ValueError("Searched for a specific peer, but got multiple returned from BIRD?")
        else:
            return peers[0]


    def _parse_peer_data(self, data, data_contains_detail):
        lineiterator = iter(data.splitlines())
        peers = []
        
        peer_summary = None
        
        for line in lineiterator:
            line = line.strip()
            (field_number, line) = self._extract_field_number(line)

            if field_number in self.ignored_field_numbers:
                continue
            
            if field_number == 1002:
                peer_summary = self._parse_peer_summary(line)
                if peer_summary['protocol'] != 'BGP':
                    peer_summary = None
                    continue
                    
            # If there is no detail section to be expected,
            # we are done.
            if not data_contains_detail:
                peers.append_peer_summary()
                continue
                    
            peer_detail = None
            if field_number == 1006:
                if not peer_summary:
                    # This is not detail of a BGP peer
                    continue
                
                # A peer summary spans multiple lines, read them all
                peer_detail_raw = []
                while line.strip() != "":
                    peer_detail_raw.append(line)
                    line = lineiterator.next()
                    
                peer_detail = self._parse_peer_detail(peer_detail_raw)
            
                # Save the summary+detail info in our result
                peer_detail.update(peer_summary)
                peers.append(peer_detail)
                # Do not use this summary again on the next run
                peer_summary = None
                
        return peers
        
            
    def _extract_field_number(self, line):
        """Parse the field type number from a line.
        Line must start with a number, followed by a dash or space.
        
        Returns a tuple of (field_number, cleaned_line), where field_number
        is None if no number was found, and cleaned_line is the line without
        the field number, if applicable.
        """
        matches = self.field_number_re.findall(line)
    
        if len(matches):
            field_number = int(matches[0])
            cleaned_line = self.field_number_re.sub('', line)
            return (field_number, cleaned_line)
        else:
            return (None, line)


    def _parse_peer_summary(self, line):
        """Parse the summary of a peer line, like:
        PS1      BGP      T_PS1    start  Jun13       Passive
        
        Returns a dict with the fields:
            name, protocol, last_change, state, up
            ("PS1", "BGP", "Jun13", "Passive", False)
        
        """
        elements = line.split()
        
        try:
            state = elements[5]
            up = (state.lower() == "established")
        except IndexError:
            state = None
            up = None
        
        last_change = self._calculate_datetime(elements[4])
        
        return {
            'name': elements[0],
            'protocol': elements[1],
            'last_change': last_change,
            'state': state,
            'up': up,
        }
        
    
    def _parse_peer_detail(self, peer_detail_raw):
        """Parse the detailed peer information from BIRD, like:
        
        1006-  Description:    Peering AS8954 - InTouch
          Preference:     100
          Input filter:   ACCEPT
          Output filter:  ACCEPT
          Routes:         24 imported, 23 exported, 0 preferred
          Route change stats:     received   rejected   filtered    ignored   accepted
            Import updates:             50          3          19         0          0
            Import withdraws:            0          0        ---          0          0
            Export updates:              0          0          0        ---          0
            Export withdraws:            0        ---        ---        ---          0
            BGP state:          Established
              Session:          external route-server AS4
              Neighbor AS:      8954
              Neighbor ID:      85.184.4.5
              Neighbor address: 2001:7f8:1::a500:8954:1
              Source address:   2001:7f8:1::a519:7754:1
              Neighbor caps:    refresh AS4
              Route limit:      9/1000
              Hold timer:       112/180
              Keepalive timer:  16/60

        peer_detail_raw must be an array, where each element is a line of BIRD output.

        Returns a dict with the fields, if the peering is up:
            routes_imported, routes_exported, router_id
            and all combinations of:
            [import,export]_[updates,withdraws]_[received,rejected,filtered,ignored,accepted]
            wfor which the value above is not "---"
            
        """
        result = {}
        
        route_change_fields = ["import updates", "import withdraws", "export updates", "export withdraws"]
        
        lineiterator = iter(peer_detail_raw)

        for line in lineiterator:
            line = line.strip()
            (field, value) = line.split(":", 1)
            value = value.strip()
            
            if field.lower() == "routes":
                routes = self.routes_field_re.findall(value)[0]
                result['routes_imported'] = int(routes[0])
                result['routes_exported'] = int(routes[1])
                
            if field.lower() in route_change_fields:
                (received, rejected, filtered, ignored, accepted) = value.split()
                key_name_base = field.lower().replace(' ', '_')
                self._parse_route_stats(result, key_name_base+'_received', received)
                self._parse_route_stats(result, key_name_base+'_rejected', rejected)
                self._parse_route_stats(result, key_name_base+'_filtered', filtered)
                self._parse_route_stats(result, key_name_base+'_ignored', ignored)
                self._parse_route_stats(result, key_name_base+'_accepted', accepted)
                
            if field.lower() == "neighbor id":
                result['router_id'] = value
            
        return result
    
    
    def _parse_route_stats(self, result_dict, key_name, value):
        if value.strip() == "---":
            return        
        result_dict[key_name] = int(value)
        
        
    def _calculate_datetime(self, value):
        """Turn the BIRD date format into a python datetime."""
        now = datetime.now()
        
        # Case 1: HH:mm timestamp
        try:
            parsed_value = datetime.strptime(value, "%H:%M")
            result_date = datetime(now.year, now.month, now.day, parsed_value.hour, parsed_value.minute)
            
            if now.hour <= parsed_value.hour and now.minute < parsed_value.minute:
                result_date = result_date - timedelta(days=1)
            
            return result_date
            
        except ValueError:
            # It's a different format, keep on processing
            pass
        
        # Case 2: "Jun13" timestamp
        try:
            # Run this for a leap year, or 29 feb will get us in trouble
            parsed_value = datetime.strptime("1996 "+value, "%Y %b%d")
            result_date = datetime(now.year, parsed_value.month, parsed_value.day)

            if now.month <= parsed_value.month and now.day < parsed_value.day:
                result_date = result_date - timedelta(years=1)
            
            return result_date
        except ValueError:
            pass
            
        # Must be a plain year
        try:
            year = int(value)
            return datetime(year, 1, 1)
        except ValueError:
            raise ValueError("Can not parse datetime: [%s]" % value)
        
            
        
    def _send_query(self, query):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_file)
        sock.send(query)
        
        # FIXME this may give incomplete data
        data = sock.recv(10240)
        sock.close()
        return str(data)
        
        
    def _clean_input(self, input):
        return self.clean_input_re.sub('', input).strip()
