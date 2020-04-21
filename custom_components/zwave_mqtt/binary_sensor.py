"""Representation of Z-Wave binary_sensors."""

import logging

from openzwavemqtt.const import ValueType

from homeassistant.components.binary_sensor import (
    DEVICE_CLASS_DOOR,
    DEVICE_CLASS_GAS,
    DEVICE_CLASS_HEAT,
    DEVICE_CLASS_LOCK,
    DEVICE_CLASS_MOISTURE,
    DEVICE_CLASS_MOTION,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_PROBLEM,
    DEVICE_CLASS_SAFETY,
    DEVICE_CLASS_SMOKE,
    DEVICE_CLASS_SOUND,
    BinarySensorDevice,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .entity import ZWaveDeviceEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Z-Wave binary_sensor from config entry."""

    @callback
    def async_add_binary_sensor(values):
        """Add Z-Wave Binary Sensor."""

        sensors_to_add = []

        if values.primary.type == ValueType.LIST:

            # Handle special cases
            # https://github.com/OpenZWave/open-zwave/blob/master/config/NotificationCCTypes.xml
            for item in values.primary.value["List"]:
                if values.primary.index == 6 and item["Value"] == 22:
                    # Door/Window Open
                    sensors_to_add.append(
                        ZWaveListValueSensor(values, item["Value"], DEVICE_CLASS_DOOR)
                    )
                if values.primary.index == 7 and item["Value"] in [7, 8]:
                    # Motion detected
                    sensors_to_add.append(
                        ZWaveListValueSensor(values, item["Value"], DEVICE_CLASS_MOTION)
                    )

            # generic sensor for this CCType
            sensors_to_add.append(ZWaveListSensor(values))

        elif values.primary.type == ValueType.BOOL:
            # classic/legacy binary sensor
            sensors_to_add.append(ZWaveBinarySensor(values))
        else:
            _LOGGER.warning("Sensor not implemented for value %s", values.primary.label)
            return

        async_add_entities(sensors_to_add)

    async_dispatcher_connect(hass, "zwave_new_binary_sensor", async_add_binary_sensor)

    await hass.data[DOMAIN][config_entry.entry_id]["mark_platform_loaded"](
        "binary_sensor"
    )


class ZWaveBinarySensor(ZWaveDeviceEntity, BinarySensorDevice):
    """Representation of a Z-Wave binary_sensor."""

    @property
    def is_on(self):
        """Return if the sensor is on or off."""
        return self.values.primary.value

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        product_name = self.values.primary.node.node_device_type_string
        if product_name == "Door/Window Detector":
            return DEVICE_CLASS_DOOR
        if product_name == "Motion Detector":
            return DEVICE_CLASS_MOTION
        return None


class ZWaveListSensor(ZWaveDeviceEntity, BinarySensorDevice):
    """Representation of a ZWaveListSensor translated to binary_sensor."""

    @property
    def is_on(self):
        """Return if the sensor is on or off."""
        return self.values.primary.value["Selected"] != "Clear"

    @property
    def state_attributes(self):
        """Return the device specific state attributes."""
        return {"event": self.values.primary.value["Selected"]}

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self.values.primary.index == 1:
            return DEVICE_CLASS_SMOKE
        if self.values.primary.index == 2:
            return DEVICE_CLASS_GAS
        if self.values.primary.index == 3:
            return DEVICE_CLASS_GAS
        if self.values.primary.index == 4:
            return DEVICE_CLASS_HEAT
        if self.values.primary.index == 5:
            return DEVICE_CLASS_MOISTURE
        if self.values.primary.index == 6:
            return DEVICE_CLASS_LOCK
        if self.values.primary.index == 7:
            return DEVICE_CLASS_SAFETY
        if self.values.primary.index == 8:
            return DEVICE_CLASS_POWER
        if self.values.primary.index == 9:
            return DEVICE_CLASS_PROBLEM
        if self.values.primary.index == 10:
            return DEVICE_CLASS_PROBLEM
        if self.values.primary.index == 14:
            return DEVICE_CLASS_SOUND
        if self.values.primary.index == 15:
            return DEVICE_CLASS_MOISTURE
        if self.values.primary.index == 18:
            return DEVICE_CLASS_GAS
        return None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        # We hide some of the more advanced sensors by default to not overwhelm users
        if self.values.primary.index in [8, 9]:
            return False
        return True


class ZWaveListValueSensor(ZWaveDeviceEntity, BinarySensorDevice):
    """Representation of a ZWaveListValueSensor binary_sensor."""

    def __init__(self, values, list_value, device_class=None):
        """Initilize a ZWaveListValueSensor entity."""
        self._list_value = list_value
        self._device_class = device_class
        super().__init__(values)

    @property
    def name(self):
        """Return the name of the entity."""
        node = self.values.primary.node
        value_label = ""
        for item in self.values.primary.value["List"]:
            if item["Value"] == self._list_value:
                value_label = item["Label"]
                break
        return f"{node.node_manufacturer_name} {node.node_product_name}: {value_label}"

    @property
    def unique_id(self):
        """Return the unique_id of the entity."""
        return f"{self.values.unique_id}.{self._list_value}"

    @property
    def is_on(self):
        """Return if the sensor is on or off."""
        return self.values.primary.value["Selected_id"] == self._list_value

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class
