#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import vobject
import StringIO
import uuid
from lxml import etree

from caldav.lib import error, vcal, url
from caldav.lib.url import URL
from caldav.elements import dav, cdav


class DAVObject(object):
    """
    Base class for all DAV objects.
    """
    id = None
    url = None
    client = None
    parent = None
    name = None

    def __init__(self, client, url=None, parent=None, name=None, id=None):
        """
        Default constructor.

        Parameters:
         * client: A DAVClient instance
         * url: The url for this object
         * parent: The parent object
         * name: A displayname
         * id: The resource id (UID for an Event)
        """

        self.client = client
        self.parent = parent
        self.name = name
        self.id = id
        self.url = URL.objectify(url)

    @property
    def canonical_url(self):
        return str(self.url.unauth())

    def children(self, type=None):
        """
        List children, using a propfind (resourcetype) on the parent object,
        at depth = 1.
        """
        c = []

        depth = 1
        properties = {}

        props = [dav.ResourceType(), ]
        response = self._query_properties(props, depth)

        for r in response.tree.findall(dav.Response.tag):
            href = self.url.join(URL.objectify(r.find(dav.Href.tag).text))
            # We use canonicalized urls to index children
            ## TODO ... do we need to?
            #href = url.canonicalize(href, self)
            properties[str(href.unauth())] = {}
            for p in props:
                t = r.find(".//" + p.tag)
                if len(list(t)) > 0:
                    if type is not None:
                        val = t.find(".//" + type)
                    else:
                        val = t.find(".//*")
                    if val is not None:
                        val = val.tag
                    else:
                        val = None
                else:
                    val = t.text
                properties[str(href.unauth())][p.tag] = val

        for path in properties.keys():
            resource_type = properties[path][dav.ResourceType.tag]
            if resource_type == type or type is None:
                if path != self.url:
                    c.append((path, resource_type))

        return c

    def _query_properties(self, props=[], depth=0):
        body = ""
        # build the propfind request
        if len(props) > 0:
            prop = dav.Prop() + props
            root = dav.Propfind() + prop

            body = etree.tostring(root.xmlelement(), encoding="utf-8",
                                  xml_declaration=True)

        return self.client.propfind(self.url, body, depth)

    def _get_properties(self, props=[], depth=0):
        properties = {}

        response = self._query_properties(props, depth)

        # All items should be in a <D:response> element
        for r in response.tree.findall(dav.Response.tag):
            href = r.find(dav.Href.tag).text
            properties[href] = {}
            for p in props:
                t = r.find(".//" + p.tag)
                if len(list(t)) > 0:
                    val = t.find(".//*")
                    if val is not None:
                        ## I assume this is a bug?
                        #val = val.tag
                        val = val.text
                    else:
                        val = None
                else:
                    val = t.text
                properties[href][p.tag] = val

        return properties

    def get_properties(self, props=[], depth=0):
        """
        Get properties (PROPFIND) for this object. Works only for
        properties, that don't have complex types.

        Parameters:
         * props = [dav.ResourceType(), dav.DisplayName(), ...]

        Returns:
         * {proptag: value, ...}
        """
        rc = None
        properties = self._get_properties(props, depth)
        path = self.url.path
        exchange_path = self.url.path + '/'

        if path in properties.keys():
            rc = properties[path]
        elif exchange_path in properties.keys():
            rc = properties[exchange_path]
        else:
            raise Exception("The CalDAV server you are using has "
                            "a problem with path handling.")

        return rc

    def set_properties(self, props=[]):
        """
        Set properties (PROPPATCH) for this object.

        Parameters:
         * props = [dav.DisplayName('name'), ...]

        Returns:
         * self
        """
        prop = dav.Prop() + props
        set = dav.Set() + prop
        root = dav.PropertyUpdate() + set

        q = etree.tostring(root.xmlelement(), encoding="utf-8",
                           xml_declaration=True)
        r = self.client.proppatch(self.url.path, q)

        statuses = r.tree.findall(".//" + dav.Status.tag)
        for s in statuses:
            if not s.text.endswith("200 OK"):
                raise error.PropsetError(r.raw)

        return self

    def save(self):
        """
        Save the object. This is an abstract methed, that all classes
        derived .from DAVObject implement.

        Returns:
         * self
        """
        raise NotImplementedError()

    def delete(self):
        """
        Delete the object.
        """
        if self.url is not None:
            path = self.url.path
            r = self.client.delete(path)

            #TODO: find out why we get 404
            if r.status not in (200, 204, 404):
                raise error.DeleteError(r.raw)

    def __str__(self):
        return str(self.url)

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self.url)


class CalendarSet(DAVObject):
    def calendars(self):
        """
        List all calendar collections in this set.

        Returns:
         * [Calendar(), ...]
        """
        cals = []

        data = self.children(cdav.Calendar.tag)
        for c_url, c_type in data:
            cals.append(Calendar(self.client, c_url, parent=self))

        return cals

    def calendar(self, name=None, cal_id=None):
        """
        The calendar method will return a calendar object.  It will not initiate any communication with the server.
        """
        return Calendar(self.client, name=name, parent = self,
                        url = self.url.join(cal_id))


class Principal(DAVObject):
    """
    This class represents a DAV Principal. It doesn't do much, except
    keep track of the URLs for the calendar-home-set, etc.
    """
    def __init__(self, client, url=None):
        """
        url input is for backward compatibility and should normally be avoided.

        If url is not given, deduct principal path as well as calendar home set path from doing propfinds.
        """
        self.client = client
        self._calendar_home_set = None

        ## backwards compatibility.  
        if url is not None:
            self.url = client.url.join(URL.objectify(url))
        else:
            self.url = self.client.url
            cup = self.get_properties([dav.CurrentUserPrincipal()])
            self.url = self.client.url.join(URL.objectify(cup['{DAV:}current-user-principal']))

    def calendar(self, name=None, cal_id=None):
        """
        The calendar method will return a calendar object.  It will not initiate any communication with the server.
        """
        return self.calendar_home_set.calendar(name, cal_id)

    @property
    def calendar_home_set(self):
        if not self._calendar_home_set:
            chs = self.get_properties([cdav.CalendarHomeSet()])
            self.calendar_home_set = chs['{urn:ietf:params:xml:ns:caldav}calendar-home-set']
        return self._calendar_home_set

    @calendar_home_set.setter
    def calendar_home_set(self, url):
        if isinstance(url, CalendarSet):
            self._calendar_home_set = url
        else:
            self._calendar_home_set = CalendarSet(self.client, self.client.url.join(URL.objectify(url)))

    def calendars(self):
        return self.calendar_home_set.calendars()

class Calendar(DAVObject):
    """
    The `Calendar` object is used to represent a calendar collection.
    Refer to the RFC for details: http://www.ietf.org/rfc/rfc4791.txt
    """
    def _create(self, name, id=None):
        """
        Create a new calendar with display name `name` in `parent`.
        """
        path = None
        if id is None:
            id = str(uuid.uuid1())

        name = dav.DisplayName(name)
        cal = cdav.CalendarCollection()
        coll = dav.Collection() + cal
        type = dav.ResourceType() + coll

        prop = dav.Prop() + [type, name]
        set = dav.Set() + prop

        mkcol = cdav.Mkcalendar() + set

        q = etree.tostring(mkcol.xmlelement(), encoding="utf-8",
                           xml_declaration=True)
        path = self.parent.url.join(id)

        r = self.client.mkcalendar(path, q)
        if r.status != 201:
            raise error.MkcalendarError(r.raw)

        return (id, path)

    def save(self):
        """
        The save method for a calendar is only used to create it, for now.
        We know we have to create it when we don't have a url.

        Returns:
         * self
        """
        if self.url is None:
            (id, path) = self._create(self.name, self.id)
            self.id = id
            self.url = self.client.url.join(path)
        return self

    def date_search(self, start, end=None):
        """
        Search events by date in the calendar. Recurring events are expanded
        if they have an occurence during the specified time frame.

        Parameters:
         * start = datetime.today().
         * end = same as above.

        Returns:
         * [Event(), ...]
        """
        matches = []

        # build the request
        expand = cdav.Expand(start, end)
        data = cdav.CalendarData() + expand
        prop = dav.Prop() + data

        range = cdav.TimeRange(start, end)
        vevent = cdav.CompFilter("VEVENT") + range
        vcalendar = cdav.CompFilter("VCALENDAR") + vevent
        filter = cdav.Filter() + vcalendar

        root = cdav.CalendarQuery() + [prop, filter]

        q = etree.tostring(root.xmlelement(), encoding="utf-8",
                           xml_declaration=True)
        response = self.client.report(self.url.path, q, 1)
        for r in response.tree.findall(".//" + dav.Response.tag):
            status = r.find(".//" + dav.Status.tag)
            if status.text.endswith("200 OK"):
                href = URL.objectify(r.find(dav.Href.tag).text)
                href = self.url.join(href)
                data = r.find(".//" + cdav.CalendarData.tag).text
                e = Event(self.client, url=href, data=data, parent=self)
                matches.append(e)
            else:
                raise error.ReportError(response.raw)

        return matches

    def event(self, uid):
        """
        Get one event from the calendar.

        Parameters:
         * uid: the event uid

        Returns:
         * Event() or None
        """
        e = None

        data = cdav.CalendarData()
        prop = dav.Prop() + data

        match = cdav.TextMatch(uid)
        propf = cdav.PropFilter("UID") + match
        vevent = cdav.CompFilter("VEVENT") + propf
        vcalendar = cdav.CompFilter("VCALENDAR") + vevent
        filter = cdav.Filter() + vcalendar

        root = cdav.CalendarQuery() + [prop, filter]

        q = etree.tostring(root.xmlelement(), encoding="utf-8",
                           xml_declaration=True)
        response = self.client.report(self.url.path, q, 1)
        r = response.tree.find(".//" + dav.Response.tag)
        if r is not None:
            href = URL.objectify(r.find(".//" + dav.Href.tag).text)
            href = url.canonicalize(href, self)
            data = r.find(".//" + cdav.CalendarData.tag).text
            e = Event(self.client, url=href, data=data, parent=self)
        else:
            raise error.NotFoundError(response.raw)

        return e

    def events(self):
        """
        List all events from the calendar.

        Returns:
         * [Event(), ...]
        """
        all = []

        data = self.children()
        for e_url, e_type in data:
            all.append(Event(self.client, e_url, parent=self))

        return all

class Event(DAVObject):
    """
    The `Event` object is used to represent an event.
    """
    _instance = None
    _data = None

    def __init__(self, client, url=None, data=None, parent=None, id=None):
        """
        Event has an additional parameter for its constructor:
         * data = "...", vCal data for the event
        """
        DAVObject.__init__(self, client=client, url=url, parent=parent, id=id)
        if data is not None:
            self.data = data

    def load(self):
        """
        Load the event from the caldav server.
        """
        r = self.client.request(self.url.path)
        self.data = vcal.fix(r.raw)
        return self

    def _create(self, data, id=None, path=None):
        if id is None:
            id = str(uuid.uuid1())
        if path is None:
            path = id + ".ics"
        path = self.parent.url.join(path)
        r = self.client.put(path, data,
                            {"Content-Type": 'text/calendar; charset="utf-8"'})

        if not (r.status in (204, 201)):
            raise error.PutError(r.raw)

        return (id, path)

    def save(self):
        """
        Save the event, can be used for creation and update.

        Returns:
         * self
        """
        if self._instance is not None:
            path = self.url.path if self.url else None
            (id, path) = self._create(self._instance.serialize(), self.id,
                     path)
            self.id = id
            self.url = self.client.url.join(URL.objectify(path))
        return self

    def __str__(self):
        return "Event: %s" % self.url

    def set_data(self, data):
        self._data = vcal.fix(data)
        self._instance = vobject.readOne(StringIO.StringIO(self._data))
        return self

    def get_data(self):
        return self._data
    data = property(get_data, set_data,
                    doc="vCal representation of the event")

    def set_instance(self, inst):
        self._instance = inst
        self._data = inst.serialize()
        return self

    def get_instance(self):
        return self._instance
    instance = property(get_instance, set_instance,
                        doc="vobject instance of the event")
