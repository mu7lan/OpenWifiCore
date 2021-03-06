from pyramid.response import Response
from pyramid.view import view_config, forbidden_view_config
from pyramid.httpexceptions import HTTPFound
from pyramid_rpc.jsonrpc import jsonrpc_method
from pyramid import httpexceptions as exc
import transaction
from datetime import datetime
import pprint
from openwifi.jobserver_config import redishost, redisport, redisdb
import redis
from wsgiproxy import Proxy

import shutil
import os

import json
from pyuci import Uci
import openwifi.jobserver.tasks as jobtask
from openwifi.utils import id_generator

from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.expression import func as sql_func

from .models import (
    AccessPoint,
    DBSession,
    OpenWrt,
    ConfigArchive,
    Templates,
    SshKey,
    OpenWifiSettings
    )

from .utils import generate_device_uuid

from pyramid.security import (
   Allow,
   Authenticated,
   remember,
   forget)

@jsonrpc_method(endpoint='api')
def hello(request):
    """ this call is used for discovery to ensure """
    return "openwifi"

@jsonrpc_method(method='uuid_generate', endpoint='api')
def uuid_generate(request, unique_identifier):
    return {'uuid': generate_device_uuid(unique_identifier) }

@jsonrpc_method(method='get_default_image_url', endpoint='api')
def get_default_image_url(request, uuid):
    node = DBSession.query(OpenWrt).get(uuid)
    if node:
        node_data = node.get_data()
        if 'base_image_url' in node_data and \
            'base_image_checksum' in node_data:
            return {'default_image' : node_data['base_image_url'],
                    'default_checksum' : node_data['base_image_checksum']}

    baseImageUrl = DBSession.query(OpenWifiSettings).get('baseImageUrl')
    baseImageChecksumUrl = DBSession.query(OpenWifiSettings).get('baseImageChecksumUrl')
    if baseImageUrl and baseImageChecksumUrl:
        return {'default_image' : baseImageUrl.value, 
                'default_checksum' : baseImageChecksumUrl.value}
    else:
        return False

# TODO transform into rest api
@jsonrpc_method(method='get_node_status', endpoint='api')
def get_node_status(request, uuid):
    r = redis.StrictRedis(host=redishost, port=redisport, db=redisdb)
    resp = {}
    status = r.hget(str(uuid), 'status')
    if status: 
        resp['status'] = status.decode()
    else:
        resp['status'] = 'no status information available'
    resp['uuid']=uuid
    if resp['status'] == 'online':
        resp['interfaces'] = json.loads(r.hget(str(uuid), 'networkstatus').decode())
    return resp

# TODO separate into update and add
@jsonrpc_method(method='device_register', endpoint='api', permission='node_add')
def device_register(request, uuid, name, address, distribution, version, proto, login, password, capabilities=[], communication_protocol=""):
    device = DBSession.query(OpenWrt).get(uuid)
    # if uuid exists, update information
    if device:
    # otherwise add new device
        device.name = name
        device.address = address
        device.distribution = distribution
        device.version = version
        device.proto = proto
        device.login = login
        device.password = password
        device.capabilities = json.dumps(capabilities)
        device.communication_protocol = communication_protocol
    else:
        ap = OpenWrt(name, address, distribution, version, uuid, login, password, False)
        ap.capabilities = json.dumps(capabilities)
        ap.communication_protocol = communication_protocol
        DBSession.add(ap)
    DBSession.flush()

    for devRegFunc in request.registry.settings['OpenWifi.onDeviceRegister']:
        devRegFunc(uuid)

@jsonrpc_method(method='device_check_registered', endpoint='api', permission='node_add')
def device_check_registered(request, uuid, name):
    """
    check if a device is already present in database. This call is used by a device to check if it must register again.
    """
    device = DBSession.query(OpenWrt).get(uuid)
    if device:
        return True
    else:
        return False
