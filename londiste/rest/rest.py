import logging
import urllib
import httpx
from datetime import datetime

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
                if params:
                    url = url + '?' + urllib.parse.urlencode(params)
                self.log.debug('REST call starting: POST %s, file=%s', url, file_name)
                with httpx.Client(verify=False, timeout=None) as client:
                    response = client.post(url, files={'file': ('file', file, 'text/plain')})
                self.log.debug('REST call completed: POST %s, status=%s', url, response.status_code)
                self.log.info('Sent data to %s, result: %s', self.rest_url, response.status_code)
                response.raise_for_status()
                content_type = response.headers.get('Content-type')
                if content_type and 'application/json' in content_type:
                    return response.json()
                else:
                    return response.text