""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""

import sqlite3
import datetime
import string
import json

import config


class DataBase (object):

    def __init__(self):
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            conn.execute("PRAGMA foreign_keys = 1")
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS clients
                        (hwId INTEGER PRIMARY KEY, name text, last_update INTEGER)''')
            c.execute('''CREATE TABLE IF NOT EXISTS log
                    (ID INTEGER PRIMARY KEY AUTOINCREMENT, hwId INTEGER, status INTEGER, timestamp INTEGER, FOREIGN KEY (hwId) REFERENCES clients(hwId) ON DELETE CASCADE ON UPDATE NO ACTION)''')
            c.execute('''CREATE TABLE IF NOT EXISTS templates
                    (ID INTEGER PRIMARY KEY AUTOINCREMENT, hwId INTEGER, name text, format text, options text, FOREIGN KEY (hwId) REFERENCES clients(hwId) ON DELETE CASCADE ON UPDATE NO ACTION)''')
        except Exception as e:
            print(e)
        else:
            conn.commit()
            conn.close()

    def write(self, client):
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            c.execute("insert or replace into clients (hwId, name, last_update) values ('{0}','{1}','{2}');".format(
                client.hwId, client.name, client.last_update))
        except Exception as e:
            print(e)
        else:
            conn.commit()
            conn.close()

    def delete_slaver(self, hwId):
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            conn.execute("PRAGMA foreign_keys = 1")
            c = conn.cursor()
            c.execute("delete from clients where hwId = {0};".format(hwId))
            conn.commit()
            conn.close()
        except Exception as e:
            conn.close()
            return '{"status": "error"}'
        return '{"status": "success"}'

    def get_slavers_list(self):
        from remote_server import Slaver
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            c.execute('SELECT * FROM clients ORDER BY hwId DESC;')
            ret = []
            for el in c.fetchall():
                client = Slaver(None, el[0], el[1])
                client.last_update = el[2]
                ret.append(client)
            conn.close()
            return ret
        except sqlite3.DatabaseError as err:
            conn.close()
            print(err)
            return None

    def save_template(self, tamplate_id, slaver_id, name, format, options):
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            if tamplate_id == -1:
                c.execute("insert into templates (hwId, name, format, options) values ('{0}','{1}','{2}','{3}');".format(
                    slaver_id, name, format, json.dumps(options)))
            else:
                c.execute("update templates set  hwId = '{1}', name = '{2}', format = '{3}', options = '{4}' where ID ='{0}';".format(
                    tamplate_id, slaver_id, name, format, json.dumps(options)))

            conn.commit()
            conn.close()
        except Exception as e:
            print(e)
            conn.close()
            return '{"status": "error"}'
        return '{"status": "success"}'

    def delete_template(self, tamplate_id):
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            c.execute("delete from  templates where ID = {0};".format(tamplate_id))
            conn.commit()
            conn.close()
        except Exception as e:
            conn.close()
            return '{"status": "error"}'
        return '{"status": "success"}'

    def get_templates(self, slaver_id):
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            c.execute(
                "SELECT * FROM templates WHERE hwId = {0}".format(slaver_id))
            ret = []
            
            for el in c.fetchall():
                ret.append('{{"id":{0},"name":"{1}","format":"{2}","options":{3}}}'.format(
                    el[0], el[2], el[3], el[4]))
            conn.close()
            return '{{"templates":[{0}]}}'.format(",".join(ret))
        except Exception as e:
            print(e)
            conn.close()
            return '{"templates":[]}'  # return empty list
    
    def log(self, slaver_id, status, timestamp):
        """ Record slaver new status to base, when it changed
            type slaver_id: int
            type status: int
            type timestamp: int
        """
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            c.execute("insert into log (hwId, status, timestamp) values ('{0}','{1}','{2}');".format(
                slaver_id, status, timestamp))
        except Exception as e:
            print(e)
        else:
            conn.commit()
            conn.close()

    def get_log(self, slaver_id):
        """ Returns a log for given slaver
            type slaver_id: int
        """
        try:
            conn = sqlite3.connect(config.DATABASE_NAME)
            c = conn.cursor()
            c.execute(
                "SELECT status, timestamp FROM log WHERE hwId = {0}".format(slaver_id))
            ret = []
            
            for el in c.fetchall():
                ret.append('{{"status":"{0}","timestamp":{1}}}'.format(
                    el[0], el[1]))
            conn.close()
            return '{{"log":[{0}]}}'.format(",".join(ret))
        except Exception as e:
            print(e)
            conn.close()
            return '{"log":[]}'  # return empty list



database = DataBase()
