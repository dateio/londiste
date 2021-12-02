import logging
import urllib
import ssl
import requests
from datetime import datetime
from requests_toolbelt.multipart.encoder import MultipartEncoder

__all__ = ['Rest']

class Rest:

    log = logging.getLogger('rest')

    def __init__(self, config):
        # typ skytools.Config
        self.config = config

        self.rest_debug_file = None
        # soubor pro debugovaci vystup - simuluje volani vzdaleneho REST API
        if self.config.has_option('rest_debug_file'):
            self.rest_debug_file = self.config.get('rest_debug_file')

        # Destination URL
        self.rest_url = self.config.get("rest_url")

    def call_api(self, action, file_name, params = None):
        if self.rest_debug_file:
            with open(self.rest_debug_file, 'a+') as debug_file:
                debug_file.write("%s CALL API WITH DATA from file %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), file_name))

        if self.rest_url:
            with open(file_name, 'rb') as file:
                url = self.rest_url + action
                payload = MultipartEncoder(fields={'file': ('file', file, 'text/plain')})
                if params:
                    url = url + '?' + urllib.parse.urlencode(params)
                response = requests.post(url, data=payload, headers={'Content-Type': payload.content_type}, verify=False)
                self.log.info('Sent data to %s, result: %s', self.rest_url, response.status_code)
                response.raise_for_status()