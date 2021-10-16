from ipaddress import IPv4Interface, IPv6Interface, ip_interface, ip_network, ip_address
from re import fullmatch
from logging import getLogger
from os.path import isdir, isfile, join
from copy import deepcopy

from vnet_manager.utils.mac import random_mac_generator
from vnet_manager.conf import settings

logger = getLogger(__name__)


class ValidateConfig:
    """
    Validates the config generated by get_config() and updates some values if missing
    """

    def __init__(self, config: dict):
        """
        :param dict config: The config generated by get_config()
        """
        self._all_ok = True
        self._validators_ran = 0
        self._new_config = deepcopy(config)
        self.default_message = ". Please check your settings"
        self.config = config

    def __str__(self) -> str:
        return "VNet config validator, current_state: {}, amount of validators run: {}".format(
            "OK" if self._all_ok else "NOT OK", self._validators_ran
        )

    @property
    def config_validation_successful(self) -> bool:
        """
        This property can be called to see if any unrecoverable errors in the config have been found
        """
        return self._all_ok

    @property
    def updated_config(self) -> dict:
        """
        This property contains a updated config dict, with all values that have been fixed by this validator
        """
        return self._new_config

    @property
    def validators_ran(self) -> int:
        """
        Return the amount of validators that have been run
        """
        return self._validators_ran

    def validate(self):
        """
        Run all validation functions
        """
        self._all_ok = True
        self.validate_switch_config()
        self.validate_machine_config()
        if "veths" in self.config:
            self.validate_veth_config()

    def validate_switch_config(self):
        """
        Validates the switch part of the config
        """
        self._validators_ran += 1
        if "switches" not in self.config:
            logger.error("Config item 'switches' missing{}".format(self.default_message))
            self._all_ok = False
        elif not isinstance(self.config["switches"], int):
            logger.error(
                "Config item 'switches: {}' does not seem to be an integer{}".format(self.config["switches"], self.default_message)
            )
            self._all_ok = False

    def validate_machine_config(self):
        # TODO: Refactor
        # pylint: disable=too-many-branches
        """
        Validates the machines part of the config
        """
        self._validators_ran += 1
        if "machines" not in self.config:
            logger.error("Config item 'machines' missing{}".format(self.default_message))
            self._all_ok = False
        elif not isinstance(self.config["machines"], dict):
            logger.error("Machines config is not a dict, this means the user config is incorrect{}".format(self.default_message))
            self._all_ok = False
        else:
            for name, values in self.config["machines"].items():
                if "type" not in values:
                    logger.error("Type not found for machine {}{}".format(name, self.default_message))
                    self._all_ok = False
                elif values["type"] not in settings.SUPPORTED_MACHINE_TYPES:
                    logger.error(
                        "Type {} for machine {} unsupported. I only support the following types: {}{}".format(
                            values["type"], name, settings.SUPPORTED_MACHINE_TYPES, self.default_message
                        )
                    )
                    self._all_ok = False

                # Files
                if "files" in values:
                    if not isinstance(values["files"], dict):
                        logger.error("Files directive for machine {} is not a dict{}".format(name, self.default_message))
                        self._all_ok = False
                    else:
                        # Check the files
                        self.validate_machine_files_parameters(name)

                # Interfaces
                if "interfaces" not in values:
                    logger.error("Machine {} does not appear to have any interfaces{}".format(name, self.default_message))
                    self._all_ok = False
                elif not isinstance(values["interfaces"], dict):
                    logger.error(
                        "The interfaces for machine {} are not given as a dict, this usually means a typo in the config{}".format(
                            name, self.default_message
                        )
                    )
                    self._all_ok = False
                else:
                    self.validate_interface_config(name)

                # VLANs?
                if "vlans" not in values:
                    logger.debug("Machine {} does not appear to have any VLAN interfaces, that's okay".format(name))
                elif not isinstance(values["vlans"], dict):
                    logger.error(
                        "Machine {} has a VLAN config but it does not "
                        "appear to be a dict, this usually means a typo in the config{}".format(name, self.default_message)
                    )
                    self._all_ok = False
                else:
                    self.validate_vlan_config(name)

                # Bridges?
                if "bridges" not in values:
                    logger.debug("Machine {} does not appear to have any Bridge interfaces, that's okay".format(name))
                elif not isinstance(values["bridges"], dict):
                    logger.error(
                        "Machine {} has a bridge config defined, but it is not a dictionary, "
                        "this usally means a typo in the config{}".format(name, self.default_message)
                    )
                    self._all_ok = False
                else:
                    self.validate_machine_bridge_config(name)

    def validate_vlan_config(self, machine):
        """
        Validates the VLAN config of a particular machine
        :param machine: str: the machine to validate the VLAN config for
        """
        vlans = self.config["machines"][machine]["vlans"]
        for name, values in vlans.items():
            if "id" not in values:
                logger.error("VLAN {} on machine {} is missing it's vlan id{}".format(name, machine, self.default_message))
                self._all_ok = False
            else:
                try:
                    self._new_config["machines"][machine]["vlans"][name]["id"] = int(values["id"])
                except ValueError:
                    logger.error(
                        "Unable to cast VLAN {} with ID {} from machine {} to a integer{}".format(
                            name, values["id"], machine, self.default_message
                        )
                    )
                    self._all_ok = False
            if "link" not in values:
                logger.error("VLAN {} on machine {} is missing it's link attribute{}".format(name, machine, self.default_message))
                self._all_ok = False
            elif not isinstance(values["link"], str):
                logger.error(
                    "Link {} for VLAN {} on machine {}, does not seem to be a string{}".format(
                        values["link"], name, machine, self.default_message
                    )
                )
                self._all_ok = False
            # This check requires a valid interface config, so we only do it if the previous checks have been successful
            elif self._all_ok and values["link"] not in self.config["machines"][machine]["interfaces"]:
                logger.error(
                    "Link {} for VLAN {} on machine {} does not correspond to any interfaces on the same machine{}".format(
                        values["link"], name, machine, self.default_message
                    )
                )
                self._all_ok = False
            if "addresses" not in values:
                logger.debug("VLAN {} on machine {} does not have any addresses, that's okay".format(name, machine))
            elif not isinstance(values["addresses"], list):
                logger.error(
                    "Addresses on VLAN {} for machine {}, does not seem to be a list{}".format(name, machine, self.default_message)
                )
                self._all_ok = False
            else:
                for address in values["addresses"]:
                    try:
                        ip_interface(address)
                    except ValueError as e:
                        logger.error(
                            "Address {} for VLAN {} on machine {} does not seem to be a valid address, got parse error {}".format(
                                address, name, machine, e
                            )
                        )
                        self._all_ok = False

    def validate_machine_files_parameters(self, machine: str):
        """
        Validates the files config of a particular machine
        Assumes the files dict exists for that machine
        :param str machine: The machine to validates the files config for
        """
        files = self.config["machines"][machine]["files"]
        for host_file in files.keys():
            # First check if the user gave a relative dir from the config dir
            if isdir(join(self.config["config_dir"], host_file)) or isfile(join(self.config["config_dir"], host_file)):
                logger.debug(
                    "Updating relative host_file path {} to full path {}".format(host_file, join(self.config["config_dir"], host_file))
                )
                self._new_config["machines"][machine]["files"][join(self.config["config_dir"], host_file)] = self._new_config["machines"][
                    machine
                ]["files"].pop(host_file)
            # Check for absolute paths
            elif not isdir(host_file) or not isfile(host_file):
                logger.error(
                    "Host file {} for machine {} does not seem to be a dir or a file{}".format(host_file, machine, self.default_message)
                )
                self._all_ok = False

    def validate_interface_config(self, machine: str):
        # TODO: Refactor
        # pylint: disable=too-many-branches
        """
        Validates the interface config of a particular machine
        Assumes the interfaces dict exists for that machine
        :param str machine: the machine to validate the interfaces config for
        """
        interfaces = self.config["machines"][machine]["interfaces"]
        for int_name, int_vals in interfaces.items():
            if "ipv4" not in int_vals:
                logger.debug(
                    "No IPv4 found for interface {} on machine {}. That's okay, no IPv4 will be configured".format(int_name, machine)
                )
            else:
                # Validate the given IP
                try:
                    IPv4Interface(int_vals["ipv4"])
                except ValueError as e:
                    logger.error("Unable to parse IPv4 address {} for machine {}. Parse error: {}".format(int_vals["ipv4"], machine, e))
                    self._all_ok = False
            if "ipv6" not in int_vals:
                logger.debug(
                    "No IPv6 found for interface {} on machine {}, that's okay no IPv6 address will be configured".format(int_name, machine)
                )
            else:
                # Validate the given IP
                try:
                    IPv6Interface(int_vals["ipv6"])
                except ValueError as e:
                    logger.error("Unable to parse IPv6 address {} for machine {}. Parse error: {}".format(int_vals["ipv6"], machine, e))
                    self._all_ok = False
            if "mac" not in int_vals:
                logger.debug("MAC not found for interface {} on machine {}, generating a random one".format(int_name, machine))
                self._new_config["machines"][machine]["interfaces"][int_name]["mac"] = random_mac_generator()
            # From: https://stackoverflow.com/a/7629690/8632038
            elif not fullmatch(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", int_vals["mac"]):
                logger.error(
                    "MAC {} for interface {} on machine {}, does not seem to be valid{}".format(
                        int_vals["mac"], int_name, machine, self.default_message
                    )
                )
                self._all_ok = False
            if "bridge" not in int_vals:
                logger.error("bridge keyword missing on interface {} for machine {}{}".format(int_name, machine, self.default_message))
                self._all_ok = False
            elif not isinstance(int_vals["bridge"], int) or int_vals["bridge"] > self.config["switches"] - 1:
                logger.error(
                    "Invalid bridge number detected for interface {} on machine {}. "
                    "The bridge keyword should correspond to the interface number of the vnet bridge to connect to "
                    "(starting at iface number 0)".format(int_name, machine)
                )
                self._all_ok = False
            if "routes" in int_vals:
                if not isinstance(int_vals["routes"], list):
                    logger.error(
                        "routes passed to interface {} for machine {}, found type {}, expected type 'list'{}".format(
                            int_name, machine, type(int_vals["routes"]).__name__, self.default_message
                        )
                    )
                    self._all_ok = False
                else:
                    self.validate_interface_routes(int_vals["routes"], int_name, machine)

    def validate_interface_routes(self, routes: list, int_name: str, machine: str):
        for idx, route in enumerate(routes):
            if "to" not in route:
                logger.error(
                    "'to' keyword missing from route {} on interface {} for machine {}{}".format(
                        idx + 1, int_name, machine, self.default_message
                    )
                )
                self._all_ok = False
            else:
                try:
                    ip_network(route["to"])
                except ValueError:
                    if route["to"] == "default":
                        logger.debug(
                            "Updating 'default' to destination for route {} on interface {} for machine "
                            "{} to 0.0.0.0/0 for backwards compatibility".format(idx + 1, int_name, machine)
                        )
                        self._new_config["machines"][machine]["interfaces"][int_name]["routes"][idx]["to"] = "0.0.0.0/0"
                    else:
                        logger.error(
                            "Invalid 'to' value {} for route {} on interface {} for machine {}{}".format(
                                route["to"], idx + 1, int_name, machine, self.default_message
                            )
                        )
                        self._all_ok = False
            if "via" not in route:
                logger.error(
                    "'via' keyword missing from route {} on interface {} for machine {}{}".format(
                        idx + 1, int_name, machine, self.default_message
                    )
                )
                self._all_ok = False
            else:
                try:
                    ip_address(route["via"])
                except ValueError:
                    logger.error(
                        "Invalid 'via' value {} (not an IP address) for route {} on interface {} for machine {}{}".format(
                            route["via"], idx + 1, int_name, machine, self.default_message
                        )
                    )
                    self._all_ok = False

    def validate_machine_bridge_config(self, machine: str):
        bridges = self.config["machines"][machine]["bridges"]
        for br_name, br_vals in bridges.items():
            if "ipv4" not in br_vals:
                logger.debug("Bridge {} on machine {} has no IPv4 assigned, that's okay".format(br_name, machine))
            else:
                # Validate the given IP
                try:
                    IPv4Interface(br_vals["ipv4"])
                except ValueError as e:
                    logger.error("Unable to parse IPv4 address for bridge {} on machine {}, got error: {}".format(br_name, machine, e))
                    self._all_ok = False
            if "ipv6" not in br_vals:
                logger.debug("Bridge {} on machine {} has no IPv6 address, that's okay".format(br_name, machine))
            else:
                try:
                    # Validate the IPv6 address
                    IPv6Interface(br_vals["ipv6"])
                except ValueError as e:
                    logger.error("Unable to parse IPv6 address for bridge {} on machine {}, got error: {}".format(br_name, machine, e))
                    self._all_ok = False
            if "slaves" not in br_vals:
                logger.error("Bridge {} on machine {} does not have any slaves".format(br_name, machine))
                self._all_ok = False
            elif not isinstance(br_vals["slaves"], list):
                logger.error("Slaves on bridge {} for machine {}, is not formatted as a list".format(br_name, machine))
                self._all_ok = False
            else:
                # For each slave, check if the interface exists
                for slave in br_vals["slaves"]:
                    if slave not in self.config["machines"][machine]["interfaces"].keys():
                        logger.error("Undefined slave interface {} assigned to bridge {} on machine {}".format(slave, br_name, machine))
                        self._all_ok = False

    def validate_veth_config(self):
        """
        Validates the veth config if present
        """
        if "veths" not in self.config:
            logger.warning("Tried to validate veth config, but no veth config present, skipping...")
            return
        if not isinstance(self.config["veths"], dict):
            logger.error("Config item: 'veths' does not seem to be a dict {}".format(self.default_message))
            self._all_ok = False
            return
        for name, values in self.config["veths"].items():
            if not isinstance(name, str):
                logger.error("veth interface name: {} does not seem to be a string{}".format(name, self.default_message))
                self._all_ok = False
            elif not isinstance(values, dict):
                logger.error("veth interface {} data does not seem to be a dict{}".format(name, self.default_message))
                self._all_ok = False
            else:
                if "bridge" not in values:
                    logger.error("veth interface {} is missing the bridge parameter{}".format(name, self.default_message))
                    self._all_ok = False
                elif not isinstance(values["bridge"], str):
                    logger.error("veth interface {} bridge parameter does not seem to be a str{}".format(name, self.default_message))
                    self._all_ok = False
                if "peer" not in values:
                    logger.debug("veth interface {} does not have a peer, that's ok, assuming it's peer is defined elsewhere".format(name))
                elif not isinstance(values["peer"], str):
                    logger.error("veth interface {} peer parameter does not seem to be a string{}".format(name, self.default_message))
                    self._all_ok = False
                if "stp" not in values:
                    logger.debug("veth interface {} as no STP parameter, that's okay".format(name))
                elif not isinstance(values["stp"], bool):
                    logger.error("veth interface {} stp parameter does not seem to be a boolean{}".format(name, self.default_message))
                    self._all_ok = False
