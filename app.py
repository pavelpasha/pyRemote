
""" Created on 10.06.2020.
@author: Pavel Saenko
@email: pasha03.92@mail.ru
"""

from flask import Flask,render_template,request,send_from_directory, redirect
import random
import os
import threading
#from flask_cors import CORS
from remote_server import RemoteServer
import config
import logging
from database import database


class HTTPServer (object):
    def __init__(self):

        app = Flask(__name__)
        #cors = CORS(app, resources={r"/*": {"origins": "*"}})

        app.config.update(
            DEBUG = False,
            SECRET_KEY = 'secret_xxx'
        )
    
                   
        @app.route('/')
        def get_index_page():
            return render_template(
                'index.html'
            )
        
        @app.route('/log')
        def get_log_page():
            id = int(request.args.get('hwId'))
            name = rem_server.get_slaver_name(id)
            return render_template( 'log.html', hwId = id, name = name)

        @app.route('/api/get_online_clients')
        def get_online_clients():
            return rem_server.get_slavers_list()

        
        @app.route('/api/open_tunnel', methods=['POST'])
        def open_tunnel():
            options = request.json
            return rem_server.open_tunnel(options)

        @app.route('/api/close_tunnel')
        def close_tunnel():
            tunnel_id = int(request.args.get('tunnel_id'))
            return rem_server.close_tunnel(tunnel_id)
        
        @app.route('/api/get_client_status')
        def get_slaver_status():
            id = int(request.args.get('id'))
            return rem_server.get_slaver_status(id)

        @app.route('/api/delete_slaver')
        def delete_slaver():
            id = int(request.args.get('id'))
            return rem_server.remove_slaver(id)

        @app.route('/api/get_templates')
        def get_templates():
            id = int(request.args.get('id'))
            return database.get_templates(id)
        
        @app.route('/api/save_template', methods=['POST'])
        def save_template():
            template = request.json
            return database.save_template(template["id"],template["hwid"],template["name"], template["format"], template["options"])

        @app.route('/api/delete_template')
        def delete_template():
            template_id = int(request.args.get('template_id'))
            return database.delete_template(template_id)

        @app.route('/api/get_log')
        def get_log():
            hwId = int(request.args.get('hwId'))
            return database.get_log(hwId)
            

        @app.errorhandler(404)
        def page_not_found(e):
            # note that we set the 404 status explicitly
            return render_template('404.html'), 404

        @app.route('/favicon.ico')
        def favicon():
            return send_from_directory(os.path.join(app.root_path, 'static'),
                                'favicon.ico',mimetype='image/vnd.microsoft.icon')

   
        app.run(host='0.0.0.0', port = config.HTTP_SERVER_PORT)
   

if  __name__ == "__main__":
    global rem_server
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    logging.getLogger().setLevel(logging.DEBUG)
    rem_server = RemoteServer(config.TUNNEL_SERVER_PORT)
    HTTPServer()
    
    