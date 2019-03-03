"""
Local API support for the EAGLE-200 Energy Gateway from Rainforest Automation

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/sensor.eagl200/
"""
import logging
from datetime import timedelta, datetime
from collections import namedtuple

import voluptuous as vol
from requests.exceptions import ConnectTimeout, HTTPError
from requests.exceptions import ConnectionError as ConnectError

from homeassistant.components.sensor import PLATFORM_SCHEMA, DOMAIN
from homeassistant.const import (CONF_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_EXCLUDE,
                                 ATTR_UNIT_OF_MEASUREMENT, ATTR_DEVICE_CLASS,
                                 DEVICE_CLASS_TIMESTAMP)
from homeassistant.util import Throttle
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv



REQUIREMENTS = ['rfa-eagle-api==0.0.5']

_LOGGER = logging.getLogger(__name__)

#    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_EXCLUDE, default=[]):
        vol.All(cv.ensure_list, [cv.string]),
})

# Prevent excessive device queries
MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=10)

# Device Attributes
LAST_CONTACT = 'last_contact'
CONNECTION_STATUS = 'connection_status'

# Units
UNIT_KW = 'kW'
UNIT_KWH = 'kWh'
UNIT_PRICE = '$'
UNIT_MINUTE = 'min'

# Icons
ICON_POWER = 'mdi:flash'
ICON_TIME = 'mdi:clock-outline'
ICON_PRICE = 'mdi:currency-usd'
ICON_DURATION = 'mdi:timelapse'

def _ms_to_iso8601(milliseconds):
    """Convert ms to ISO8601"""
    return datetime.fromtimestamp(int(milliseconds)).isoformat()


# Provide sensor-specific customization
SensorConfig = namedtuple('SensorConfig',
                          ['name', 'field', 'units', 'icon', 'device_class', 'value_formatter'])
SENSORS = [
    SensorConfig(
        name='Instaneous Demand',
        field="instantaneous_demand",
        units=UNIT_KW,
        icon=ICON_POWER,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name='Current Summation Delivered',
        field="current_summation_delivered",
        units=UNIT_KWH,
        icon=ICON_POWER,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name='Current Summation Received',
        field="current_summation_received",
        units=UNIT_KWH,
        icon=ICON_POWER,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Price",
        field="price",
        units=UNIT_PRICE,
        icon=ICON_PRICE,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Rate Label",
        field="rate_label",
        units=None,
        icon=ICON_PRICE,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Price Tier",
        field="price_tier",
        units=None,
        icon=ICON_PRICE,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Price Start Time",
        field="price_start_time",
        units=None,
        icon=ICON_TIME,
        device_class=DEVICE_CLASS_TIMESTAMP,
        value_formatter=_ms_to_iso8601
    ),
    SensorConfig(
        name="Price Duration",
        field="price_duration",
        units=UNIT_MINUTE,
        icon=ICON_DURATION,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Block Period Start",
        field="block_period_start",
        units=None,
        icon=ICON_TIME,
        device_class=DEVICE_CLASS_TIMESTAMP,
        value_formatter=_ms_to_iso8601
    ),
    SensorConfig(
        name="Block Period Duration",
        field="block_period_duration",
        units=UNIT_MINUTE,
        icon=ICON_DURATION,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Block Period Consumption",
        field="block_period_consumption",
        units=UNIT_KWH,
        icon=ICON_POWER,
        device_class=None,
        value_formatter=None
    ),
    SensorConfig(
        name="Billing Period Start",
        field="billing_period_start",
        units=None,
        icon=ICON_TIME,
        device_class=DEVICE_CLASS_TIMESTAMP,
        value_formatter=_ms_to_iso8601
    ),
    SensorConfig(
        name="Billing Period Duration",
        field="billing_period_duration",
        units=UNIT_MINUTE,
        icon=ICON_DURATION,
        device_class=None,
        value_formatter=None
    ),
]


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up all Duke Energy meters."""
    #from pydukeenergy.api import DukeEnergy, DukeEnergyException
    from eagle.localapi import LocalApi, Meter

    _LOGGER.debug("Setting up EAGLE-200 LocalApi sensor")
    try:
        api = LocalApi(host=config[CONF_HOST],
                       username=config[CONF_USERNAME],
                       password=config[CONF_PASSWORD])

        # Find meters connected to Eagle gateway and wrap in helper class
        meters = [EagleMeter(meter) for meter in Meter.get_meters(api)]

        _LOGGER.info('Found %d meters.', len(meters))

        exclude = config[CONF_EXCLUDE]

        # Create a sensor entities for configured sensors and meters
        entities = [MeterSensorVariable(meter, **sensor._asdict())
                    for meter in meters
                    for sensor in SENSORS
                    if sensor.field not in exclude]

        # Add Price Blocks
        for meter in meters:
            num_blocks = len(meter.meter.blocks)
            for i in range(1, 1 + num_blocks):
                field_name = "block{}_price".format(i)
                if field_name not in exclude:
                    entities.append(
                        MeterSensorVariable(meter, field_name,
                                            name="Block {} Price".format(i),
                                            units=UNIT_PRICE, icon=ICON_PRICE),
                    )

                # Don't add last threshold as it will always be empty
                field_name = "block{}_threshold".format(i)
                if field_name not in exclude and i < num_blocks:
                    entities.append(
                        MeterSensorVariable(meter, field_name,
                                            name="Block {} Threshold".format(i),
                                            units=UNIT_KWH, icon=ICON_POWER),
                    )


        add_entities(entities)

    except (ConnectError, ConnectTimeout, HTTPError) as ex:
        _LOGGER.error("Unable to connect to EAGLE device: %s", str(ex))
        return False

    return True


class MeterSensorVariable(Entity):
    """Represents a meter variable"""
    def __init__(self, eagle_meter, field, name=None,
                 units=None, icon=None, device_class=None, value_formatter=None):
        self.eagle_meter = eagle_meter
        self.meter_field = field
        self._name = name
        self._units = units
        self._icon = icon
        self._device_class = device_class
        self._value_formatter = value_formatter

        self._unique_id = self._generate_unique_id()


    def _generate_unique_id(self):
        return "{}_{}".format(self.eagle_meter.device.hardware_address, self.meter_field)

    @property
    def unique_id(self):
        """Return the unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name."""
        if self._name is not None:
            return self._name

        return "eagle_" + self.unique_id



    def update(self):
        """Update sensor variable. Delegated to meter."""
        self.eagle_meter.update()


    @property
    def state(self):
        """Return state."""
        value = self.eagle_meter.get_value(self.meter_field)
        if self._value_formatter:
            return self._value_formatter(value)

        return value

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement this sensor expresses itself in."""
        return self._units

    @property
    def device_class(self) -> str:
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._icon

    @property
    def device_info(self):
        return {
            'identifiers': {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.eagle_meter.device.hardware_address)
            },
            'name': "eagle_{}".format(self.eagle_meter.device.hardware_address),
            'manufacturer': self.eagle_meter.device.manufacturer,
            'model': self.eagle_meter.device.model_id,
            'via_hub': (DOMAIN, self.eagle_meter.device.network_interface),
        }

    @property
    def device_state_attributes(self):
        """Return the state attributes."""

        attributes = {
            LAST_CONTACT: self.eagle_meter.device.last_contact,
            CONNECTION_STATUS: self.eagle_meter.device.connection_status,
        }
        return attributes



class EagleMeter:
    """Representation of an RFA EAGLE energy meter."""

    def __init__(self, meter):
        """Initialize the meter."""
        _LOGGER.debug('Initializing EagleElectricMeter: %s', meter.device.hardware_address)
        self._meter = meter
        self.update()

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Update meter. Calls throttled to no more than once per 10 seconds"""
        self._meter.update()
        _LOGGER.debug('device updated: %s', self.meter.device)


    def get_value(self, field_name):
        """ Get value for field from meter """
        value = getattr(self.meter, field_name)
        return value

    @property
    def meter(self):
        """ Provide access to undelying device """
        return self._meter

    @property
    def device(self):
        """ Provide access to undelying device """
        return self.meter.device
