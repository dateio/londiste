import logging
import urllib
import urllib2
import ssl
from datetime import datetime

from poster.encode import multipart_encode
from poster.streaminghttp import register_openers, StreamingHTTPSHandler, StreamingHTTPSConnection

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

        register_openers()
        if self.rest_url.lower().startswith('https'):
            self.register_SSL_unverified_http_opener()

    def call_api(self, action, file_name, params = None):
        if self.rest_debug_file:
            with open(self.rest_debug_file, 'a+') as debug_file:
                debug_file.write("%s CALL API WITH DATA from file %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), file_name))

        if self.rest_url:
            with open(file_name, 'rb') as file:
                datagen, headers = multipart_encode({'file': file})
                url = self.rest_url + action
                if params:
                    url = url + '?' + urllib.urlencode(params)
                request = urllib2.Request(url, datagen, headers)
                response = urllib2.urlopen(request)
                self.log.info('Sent data to %s, result: %s', self.rest_url, response.getcode())




    def register_SSL_unverified_http_opener(self):
        class StreamingHTTPSHandlerNoVerify(StreamingHTTPSHandler):
            def __init__(self, context=None):
                StreamingHTTPSHandler.__init__(self, context=context)
                self.handler_order -= 1

            def https_open(self, req):
                return self.do_open(StreamingHTTPSConnection, req, context = self._context)

        handler = StreamingHTTPSHandlerNoVerify(context = ssl._create_unverified_context())
        opener = urllib2.build_opener(handler)
        urllib2.install_opener(opener)
