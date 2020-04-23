"""Support for Z-Wave climate devices."""
import logging
from typing import Optional, Tuple

from openzwavemqtt.const import CommandClass

from homeassistant.components.climate import ClimateDevice
from homeassistant.components.climate.const import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_FAN,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    DOMAIN,
    HVAC_MODE_AUTO,
    HVAC_MODE_COOL,
    HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_HEAT,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    FAN_ON,
    FAN_OFF,
    FAN_AUTO,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
    SUPPORT_AUX_HEAT,
    SUPPORT_FAN_MODE,
    SUPPORT_PRESET_MODE,
    SUPPORT_SWING_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_TARGET_TEMPERATURE_RANGE,
)
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS, TEMP_FAHRENHEIT
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .entity import ZWaveDeviceEntity


REMOTEC = 0x5254
REMOTEC_ZXT_120 = 0x8377
REMOTEC_ZXT_120_THERMOSTAT = (REMOTEC, REMOTEC_ZXT_120)
ATTR_OPERATING_STATE = "operating_state"
ATTR_FAN_STATE = "fan_state"
ATTR_FAN_ACTION = "fan_action"
AUX_HEAT_ZWAVE_MODE = "Aux Heat"

# Device is in manufacturer specific mode (e.g. setting the valve manually)
PRESET_MANUFACTURER_SPECIFIC = "Manufacturer Specific"

WORKAROUND_ZXT_120 = "zxt_120"

DEVICE_MAPPINGS = {REMOTEC_ZXT_120_THERMOSTAT: WORKAROUND_ZXT_120}

HVAC_STATE_MAPPINGS = {
    "off": HVAC_MODE_OFF,
    "heat": HVAC_MODE_HEAT,
    "heat mode": HVAC_MODE_HEAT,
    "heat (default)": HVAC_MODE_HEAT,
    "furnace": HVAC_MODE_HEAT,
    "fan only": HVAC_MODE_FAN_ONLY,
    "dry air": HVAC_MODE_DRY,
    "moist air": HVAC_MODE_DRY,
    "cool": HVAC_MODE_COOL,
    "heat_cool": HVAC_MODE_HEAT_COOL,
    "auto": HVAC_MODE_HEAT_COOL,
    "auto changeover": HVAC_MODE_HEAT_COOL,
}

MODE_SETPOINT_MAPPINGS = {
    "off": (),
    "heat": ("setpoint_heating",),
    "cool": ("setpoint_cooling",),
    "auto": ("setpoint_heating", "setpoint_cooling"),
    "aux heat": ("setpoint_heating",),
    "furnace": ("setpoint_furnace",),
    "dry air": ("setpoint_dry_air",),
    "moist air": ("setpoint_moist_air",),
    "auto changeover": ("setpoint_auto_changeover",),
    "heat econ": ("setpoint_eco_heating",),
    "cool econ": ("setpoint_eco_cooling",),
    "away": ("setpoint_away_heating", "setpoint_away_cooling"),
    "full power": ("setpoint_full_power",),
    # aliases found in xml configs
    "comfort": ("setpoint_heating",),
    "heat mode": ("setpoint_heating",),
    "heat (default)": ("setpoint_heating",),
    "dry floor": ("setpoint_dry_air",),
    "heat eco": ("setpoint_eco_heating",),
    "energy saving": ("setpoint_eco_heating",),
    "energy heat": ("setpoint_eco_heating",),
    "vacation": ("setpoint_away_heating", "setpoint_away_cooling"),
    # for tests
    "heat_cool": ("setpoint_heating", "setpoint_cooling"),
}

HVAC_CURRENT_MAPPINGS = {
    "idle": CURRENT_HVAC_IDLE,
    "heat": CURRENT_HVAC_HEAT,
    "pending heat": CURRENT_HVAC_IDLE,
    "heating": CURRENT_HVAC_HEAT,
    "cool": CURRENT_HVAC_COOL,
    "pending cool": CURRENT_HVAC_IDLE,
    "cooling": CURRENT_HVAC_COOL,
    "fan only": CURRENT_HVAC_FAN,
    "vent / economiser": CURRENT_HVAC_FAN,
    "off": CURRENT_HVAC_OFF,
}

PRESET_MAPPINGS = {
    "away": PRESET_AWAY,
    "full power": PRESET_BOOST,
    "manufacturer specific": PRESET_MANUFACTURER_SPECIFIC,
}

DEFAULT_HVAC_MODES = [
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_COOL,
    HVAC_MODE_FAN_ONLY,
    HVAC_MODE_DRY,
    HVAC_MODE_OFF,
    HVAC_MODE_AUTO,
]

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Z-Wave Cover from Config Entry."""

    @callback
    def async_add_climate(values):
        """Add Z-Wave Climate."""
        climate = None
        if values.primary.command_class == CommandClass.THERMOSTAT_SETPOINT:
            climate = ZWaveClimateSingleSetpoint(values)
        elif values.primary.command_class == CommandClass.THERMOSTAT_MODE:
            climate = ZWaveClimateMultipleSetpoint(values)
        async_add_entities([climate])

    async_dispatcher_connect(hass, "zwave_new_climate", async_add_climate)
    await hass.data[DOMAIN][config_entry.entry_id]["mark_platform_loaded"]("climate")
    

class ZWaveClimateBase(ZWaveDeviceEntity, ClimateDevice):
    """Representation of a Z-Wave Climate device."""
    
    def __init__(self, values):
        ZWaveDeviceEntity.__init__(self, values)
        self._target_temperature = None
        self._target_temperature_range = (None, None)
        self._current_temperature = None
        self._hvac_action = None
        self._hvac_list = None  # [zwave_mode]
        self._hvac_mapping = None  # {ha_mode:zwave_mode}
        self._hvac_mode = None  # ha_mode
        self._aux_heat = None
        self._default_hvac_mode = None  # ha_mode
        self._preset_mapping = None  # {ha_mode:zwave_mode}
        self._preset_list = None  # [zwave_mode]
        self._preset_mode = None  # ha_mode if exists, else zwave_mode
        self._current_fan_mode = None
        self._fan_modes = None
        self._fan_action = None
        self._current_swing_mode = None
        self._swing_modes = None
        self._unit = None
        self._zxt_120 = None
        self.update_properties()
    
    @callback
    def value_changed(self,value):
        self.update()
        super().value_changed(value)
        
    def update(self):
        self.update_properties()

    def _mode(self) -> None:
        """Return thermostat mode Z-Wave value."""
        raise NotImplementedError()

    def _current_mode_setpoints(self) -> Tuple:
        """Return a tuple of current setpoint Z-Wave value(s)."""
        raise NotImplementedError()

    @property
    def supported_features(self):
        """Return the list of supported features."""
        support = SUPPORT_TARGET_TEMPERATURE
        if self._hvac_list and HVAC_MODE_HEAT_COOL in self._hvac_list:
            support |= SUPPORT_TARGET_TEMPERATURE_RANGE
        if self._preset_list and PRESET_AWAY in self._preset_list:
            support |= SUPPORT_TARGET_TEMPERATURE_RANGE
        if self.values.fan_mode:
            support |= SUPPORT_FAN_MODE
        if self._zxt_120 == 1 and self.values.zxt_120_swing_mode:
            support |= SUPPORT_SWING_MODE
        if self._aux_heat:
            support |= SUPPORT_AUX_HEAT
        if self._preset_list:
            support |= SUPPORT_PRESET_MODE
        return support
        
    def update_properties(self):
        """Handle the data changes for node values."""
        self._update_operation_mode()
        self._update_current_temp()
        self._update_fan_mode()
        self._update_swing_mode()
        self._update_target_temp()
        self._update_operating_state()
        self._update_fan_state()

    def _update_operation_mode(self):
        """Update hvac and preset modes."""
        if self._mode():
            self._hvac_list = []
            self._hvac_mapping = {}
            self._preset_list = []
            self._preset_mapping = {}
            
            mode_list = self._mode().value_list
            if mode_list:
                for mode in mode_list:
                    ha_mode = HVAC_STATE_MAPPINGS.get(str(mode).lower())
                    ha_preset = PRESET_MAPPINGS.get(str(mode).lower())
                    if mode == AUX_HEAT_ZWAVE_MODE:
                        # Aux Heat should not be included in any mapping
                        self._aux_heat = True
                    elif ha_mode and ha_mode not in self._hvac_mapping:
                        self._hvac_mapping[ha_mode] = mode
                        self._hvac_list.append(ha_mode)
                    elif ha_preset and ha_preset not in self._preset_mapping:
                        self._preset_mapping[ha_preset] = mode
                        self._preset_list.append(ha_preset)
                    else:
                        # If nothing matches
                        self._preset_list.append(mode)

            # Default operation mode
            for mode in DEFAULT_HVAC_MODES:
                if mode in self._hvac_mapping.keys():
                    self._default_hvac_mode = mode
                    break

            if self._preset_list:
                # Presets are supported
                self._preset_list.append(PRESET_NONE)

            current_mode = self._mode().value_selected
            _hvac_temp = next(
                (
                    key
                    for key, value in self._hvac_mapping.items()
                    if value == current_mode
                ),
                None,
            )

            if _hvac_temp is None:
                # The current mode is not a hvac mode
                if (
                    "heat" in current_mode.lower()
                    and HVAC_MODE_HEAT in self._hvac_mapping.keys()
                ):
                    # The current preset modes maps to HVAC_MODE_HEAT
                    self._hvac_mode = HVAC_MODE_HEAT
                elif (
                    "cool" in current_mode.lower()
                    and HVAC_MODE_COOL in self._hvac_mapping.keys()
                ):
                    # The current preset modes maps to HVAC_MODE_COOL
                    self._hvac_mode = HVAC_MODE_COOL
                else:
                    # The current preset modes maps to self._default_hvac_mode
                    self._hvac_mode = self._default_hvac_mode
                self._preset_mode = next(
                    (
                        key
                        for key, value in self._preset_mapping.items()
                        if value == current_mode
                    ),
                    current_mode,
                )
            else:
                # The current mode is a hvac mode
                self._hvac_mode = _hvac_temp
                self._preset_mode = PRESET_NONE


    def _update_current_temp(self):
        """Update current temperature."""
        if self.values.temperature:
            self._current_temperature = self.values.temperature.value
            device_unit = self.values.temperature.units
            if device_unit is not None:
                self._unit = device_unit

    def _update_fan_mode(self):
        """Update fan mode."""
        if self.values.fan_mode:
            self._current_fan_mode = self.values.fan_mode.value_selected
            fan_modes = self.values.fan_mode.value_list
            if fan_modes:
                self._fan_modes = list(fan_modes)

    def _update_swing_mode(self):
        """Update swing mode."""
        if self._zxt_120 == 1:
            if self.values.zxt_120_swing_mode:
                self._current_swing_mode = self.values.zxt_120_swing_mode.value
                swing_modes = self.values.zxt_120_swing_mode.value_list
                if swing_modes:
                    self._swing_modes = list(swing_modes)

    def _update_target_temp(self):
        """Update target temperature."""
        current_setpoints = self._current_mode_setpoints()
        self._target_temperature = None
        self._target_temperature_range = (None, None)
        if len(current_setpoints) == 1:
            (setpoint,) = current_setpoints
            if setpoint is not None:
                self._target_temperature = round((float(setpoint.value)), 1)
        elif len(current_setpoints) == 2:
            (setpoint_low, setpoint_high) = current_setpoints
            target_low, target_high = None, None
            if setpoint_low is not None:
                target_low = round((float(setpoint_low.value)), 1)
            if setpoint_high is not None:
                target_high = round((float(setpoint_high.value)), 1)
            self._target_temperature_range = (target_low, target_high)

    def _update_operating_state(self):
        """Update operating state."""
        if self.values.operating_state:
            mode = self.values.operating_state.value
            self._hvac_action = HVAC_CURRENT_MAPPINGS.get(str(mode).lower(), mode)

    def _update_fan_state(self):
        """Update fan state."""
        if self.values.fan_action:
            self._fan_action = self.values.fan_action.value

    @property
    def fan_mode(self):
        """Return the fan speed set."""
        return self._current_fan_mode

    @property
    def fan_modes(self):
        """Return a list of available fan modes."""
        return self._fan_modes

    @property
    def swing_mode(self):
        """Return the swing mode set."""
        return self._current_swing_mode

    @property
    def swing_modes(self):
        """Return a list of available swing modes."""
        return self._swing_modes

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_FAHRENHEIT

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode."""
        """Needs to be one of HVAC_MODE_*."""
        if self._mode():
            return self._hvac_mode
        return self._default_hvac_mode

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes."""
        """Need to be a subset of HVAC_MODES."""
        if self._mode():
            return self._hvac_list
        return []

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported."""
        """Needs to be one of CURRENT_HVAC_*."""
        if not self._aux_heat:
            return None
        if self._mode().data == AUX_HEAT_ZWAVE_MODE:
            return True
        return False

    @property
    def is_aux_heat(self):
        """Return true if aux heater."""
        if not self._aux_heat:
            return None
        if self._mode().data == AUX_HEAT_ZWAVE_MODE:
            return True
        return False

    @property
    def preset_mode(self):
        """Return preset operation ie. eco, away."""
        """Needs to be one of PRESET_*."""
        if self._mode():
            return self._preset_mode
        return PRESET_NONE

    @property
    def preset_modes(self):
        """Return the list of available preset operation modes.
        Need to be a subset of PRESET_MODES.
        """
        if self._mode():
            return self._preset_list
        return []

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_low(self) -> Optional[float]:
        """Return the lowbound target temperature we try to reach."""
        return self._target_temperature_range[0]

    @property
    def target_temperature_high(self) -> Optional[float]:
        """Return the highbound target temperature we try to reach."""
        return self._target_temperature_range[1]

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        """Must know if single or double setpoint"""
        current_setpoints = self._current_mode_setpoints()
        if len(current_setpoints) == 1:
            (setpoint,) = current_setpoints
            target_temp = kwargs.get(ATTR_TEMPERATURE)
            if setpoint is not None and target_temp is not None:
                setpoint.send_value(target_temp)
        elif len(current_setpoints) == 2:
            (setpoint_low, setpoint_high) = current_setpoints
            target_temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
            target_temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
            if setpoint_low is not None and target_temp_low is not None:
                setpoint_low.send_value(target_temp_low)
            if setpoint_high is not None and target_temp_high is not None:
                setpoint_high.send_value(target_temp_high)

    def set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        if not self.values.fan_mode:
            return
        self.values.fan_mode.send_value(fan_mode)

    def set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if not self._mode():
            return
        operation_mode = self._hvac_mapping.get(hvac_mode)
        self._mode().send_value(operation_mode)

    def turn_aux_heat_on(self):
        """Turn auxiliary heater on."""
        if not self._aux_heat:
            return
        operation_mode = AUX_HEAT_ZWAVE_MODE
        self._mode().send_value(operation_mode)

    def turn_aux_heat_off(self):
        """Turn auxiliary heater off."""
        if not self._aux_heat:
            return
        if HVAC_MODE_HEAT in self._hvac_mapping:
            operation_mode = self._hvac_mapping.get(HVAC_MODE_HEAT)
        else:
            operation_mode = self._hvac_mapping.get(HVAC_MODE_OFF)
        self._mode().send_value(operation_mode)

    def set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        if not self._mode():
            return
        if preset_mode == PRESET_NONE:
            # Activate the current hvac mode
            self._update_operation_mode()
            operation_mode = self._hvac_mapping.get(self._hvac_mode)
            self._mode().send_value(operation_mode)
        else:
            operation_mode = self._preset_mapping.get(preset_mode, preset_mode)
            self._mode().send_value(operation_mode)

    def set_swing_mode(self, swing_mode):
        """Set new target swing mode."""
        if self._zxt_120 == 1:
            if self.values.zxt_120_swing_mode:
                self.values.zxt_120_swing_mode.send_value(swing_mode)

    @property
    def device_state_attributes(self):
        """Return the optional state attributes."""
        data = super().device_state_attributes
        if self._fan_action:
            data[ATTR_FAN_ACTION] = self._fan_action
        return data

class ZWaveClimateSingleSetpoint(ZWaveClimateBase):
    """Representation of a single setpoint Z-Wave thermostat device."""

    def _mode(self) -> None:
        """Return thermostat mode Z-Wave value."""
        return self.values.mode

    def _current_mode_setpoints(self) -> Tuple:
        """Return a tuple of current setpoint Z-Wave value(s)."""
        return (self.values.primary,)


class ZWaveClimateMultipleSetpoint(ZWaveClimateBase):
    """Representation of a multiple setpoint Z-Wave thermostat device."""

    def _mode(self) -> None:
        """Return thermostat mode Z-Wave value."""
        return self.values.primary

    def _current_mode_setpoints(self) -> Tuple:
        """Return a tuple of current setpoint Z-Wave value(s)."""
        current_mode = str(self.values.primary.value).lower()
        setpoints_names = MODE_SETPOINT_MAPPINGS.get(current_mode, ())
        return tuple(getattr(self.values, name, None) for name in setpoints_names)