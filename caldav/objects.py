#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import copy
import urlparse
import vobject
import StringIO

from lxml import etree

import utils.vcal
from utils.namespace import ns

class DavObject:
    url = None
    client = None
    parent = None
    name = None

    def geturl(self, path = None):
        u = ""
        if self.url is not None:
            if path is None:
                u = self.url.geturl()
            else:
                u = urlparse.urlunparse((self.url.scheme, self.url.netloc, 
                                         path, self.url.params, self.url.query,
                                         self.url.fragment))
        return u

    def properties(self, props = []):
        return commands.properties(self.client, self, props)
    
    def save(self):
        raise Exception("Must be defined in subclasses")

    def append(self, client, obj):
        pass


class Principal(DavObject):
    def __init__(self, client, url):
        self.client = client
        self.url = urlparse.urlparse(url)

    def calendars(self):
        return commands.children(self.client, self, ns("D", "collection"))


class Calendar(DavObject):
    def __init__(self, client, url = None, parent = None, name = None):
        self.client = client
        self.parent = parent
        self.name = name
        if url is not None:
            self.url = urlparse.urlparse(url)


    def save(self):
        if self.url is None:
            url = commands.create_calendar(self.client, self.parent, self.name)
            if url is not None:
                self.url = urlparse.urlparse(url)
        return self

    def date_search(self, start, end = None):
        return commands.date_search(self.client, self, start, end)

    def events(self):
        return commands.children(self.client, self)

    def __str__(self):
        return "Collection: %s" % self.geturl()

class Event(DavObject):
    instance = None

    def __init__(self, client, url = None, data = None, parent = None):
        self.client = client
        self.parent = parent
        if url is not None:
            self.url = urlparse.urlparse(url)
        if data is not None:
            self.instance = vobject.readOne(StringIO.StringIO(data))

    def load(self):
        r = self.client.request(self.url.path)
        r.raw = utils.vcal.fix(r.raw)
        self.instance = vobject.readOne(StringIO.StringIO(r.raw))

    def save(self):
        if self.instance is not None:
            if self.url is None:
                url = commands.create_event(self.client, self.parent, self.instance.serialize())
                if url is not None:
                    self.url = urlparse.urlparse(url)
            else:
                #OMGTODO
                pass
        return self

    def __str__(self):
        return "Event: %s" % self.geturl()




from utils import commands
