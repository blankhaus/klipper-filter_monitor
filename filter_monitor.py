# Monitor air filter runtime and expiry
#
# Copyright (C) 2024 Blankhaus Ltd. <frederick@blankhaus.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import ast
import csv
import datetime
import logging
import math
import os
import time

SEC_PER_DAY = 86400
SEC_PER_HOUR = 3600
SEC_PER_MIN  = 60

FAN_TYPES = [ 
	"fan", 
	"fan_generic", 
	"controller_fan", 
	"heater_fan", 
	"temperature_fan" 
]

COLORS = [
    "primary",
    "secondary",
    "accent"
    "info",
    "success",
    "error",
    "warning"
]

class FilterMonitor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler(
            "klippy:connect", 
            self._handle_connect
        )
        self.printer.register_event_handler(
            "klippy:shutdown", 
            self._handle_shutdown
        )
        self.printer.register_event_handler(
            "klippy:ready", 
            self._handle_ready
        )
        self.printer.register_event_handler(
            "gcode:request_restart", 
            self._handle_restart
        )
        self.printer.register_event_handler(
            "idle_timeout:printing",
            self._handle_printing
        )
        self.printer.register_event_handler(
            "idle_timeout:idle",
            self._handle_not_printing
        )

        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        
        self.name = config.get_name().split()[-1]
        self.pretty_name = None
		
        self.fan_section = config.get("fan", "")
        self.fan_type = None
        self.fan_name = None
        self.fan = None
		
        self.max_runtime_hours = config.getfloat("max_runtime_hours", 50.0)
        self.max_days = config.getfloat("max_days", 30.0)
		
        gcode_macro = self.printer.load_object(config, "gcode_macro")
        self.expiry_gcode = None
        if config.get("expiry_gcode", None) is not None:
            self.expiry_gcode = gcode_macro.load_template(
                config, "expiry_gcode", ""
            )

        self.interval = config.getfloat("interval", 60, above=0.0)
        self.path = os.path.expanduser(config.get("path", "~/printer_data/config/plugins/filter_monitor"))
        self.file = os.path.join(self.path, self.name + ".csv")

        self.filter_last_active = None
        self.filter_last_notified = None
        self.filter_last_reset = None
        self.filter_runtime = 0.0
        self.filter_total_runtime = 0.0
        self.filter_reset_count = 0
        self.filter_active = False
        self.filter_expired = False
        self.filter_percent_r = None
        self.filter_runtime_r = None
        self.filter_days_r = None

        self.monitor_timer = None

        self.gcode.register_mux_command(
            "FILTER_STATS",
            "NAME",
            self.name,
            self.cmd_FILTER_STATS
        )
        self.gcode.register_mux_command(
            "RESET_FILTER",
            "NAME",
            self.name,
            self.cmd_RESET_FILTER
        )

    def _handle_connect(self):
        if self.fan_section is None:
            self._log_exception("Fan is required.")

        fan_split = self.fan_section.split(" ")
        if len(fan_split) != 2:
            self._log_exception("Fan is invalid.")
            
        self.fan_type, self.fan_name = fan_split
        
        if self.fan_type == "heater_generic":
            heaters = self.printer.lookup_object("heaters")
            self.fan = heaters.lookup_heater(self.fan_name)
        elif self.fan_type in FAN_TYPES: 
            self.fan = self.printer.lookup_object("fan", self.fan_name)
        else:
            self._log_exception("Fan type is unsupported.")
            
        if not os.path.exists(self.path):
            self._log_exception("Path is invalid.")

        self.pretty_name = " ".join(self.name.split("_")).title()
        
        self._restore()

    def _handle_shutdown(self):
        self._update(stop_timer=True)

    def _handle_restart(self, print_time):
        self._update(stop_timer=True)

    def _handle_printing(self, print_time):
        self._update(notify=True)
        
    def _handle_not_printing(self, print_time):
        self._update(notify=True)

    def _handle_ready(self):
        self._update(notify=False)
        self.monitor_timer = self.reactor.register_timer(
            self._monitor_event, 
            self.reactor.NOW + self.interval
        )

    def _monitor_event(self, event_time):
        return self._update(event_time)

    def _update(self, event_time = None, stop_timer=False, notify=False):
        if self.monitor_timer is not None:
            if event_time is None:
                self.reactor.update_timer(
                    self.monitor_timer, 
                    self.reactor.NEVER
                )
                
        self._monitor()
            
        if notify or (
            self.filter_expired and
            self.filter_last_notified is None and
            event_time is not None
        ):
            self._notify()

        self._persist()
            
        if self.monitor_timer is not None:
            if event_time is None and not stop_timer:
                self.reactor.update_timer(
                    self.monitor_timer,
                    self.reactor.NOW + self.interval
                )

        if event_time is not None and not stop_timer:
            return event_time + self.interval
        
        return self.reactor.NEVER
        
    def _restore(self):
        if not os.path.isfile(self.file):
            self._log_info("No persisted file found!")
            return
            
        try:
            with open(self.file, "r", newline="", encoding="utf-8") as f:
                csv_reader = csv.reader(f, delimiter=",")
                for row in csv_reader:
                    self.filter_last_reset = ast.literal_eval(row[0])
                    self.filter_runtime = ast.literal_eval(row[1])
                    self.filter_total_runtime = ast.literal_eval(row[2])
                    self.filter_reset_count = ast.literal_eval(row[3])
                    break
        except IOError as e:
            self._log_exception("%s %s" % (self.file, str(e)))
        except:
            self._log_exception("Unable to parse %s" % self.file)
 
    def _monitor(self):
        now = time.time()

        if self.filter_last_reset is None:
            self.filter_last_reset = now
            
        if self.fan_type == "heater_generic":
            self.filter_active = self.fan.last_pwm_value > 0.0
        else:
            status = self.fan.get_status(self.reactor.NOW)
            self.filter_active = status["speed"] > 0.0

        if self.filter_active:
            if self.filter_last_active is not None:
                runtime = now - self.filter_last_active
                self.filter_runtime += runtime
                self.filter_total_runtime += runtime
                
            self.filter_last_active = now
        else:
            self.filter_last_active = None

        runtime_d1 = datetime.timedelta(hours=self.max_runtime_hours)
        runtime_d2 = datetime.timedelta(seconds=self.filter_runtime)
        runtime_d = (runtime_d1 - runtime_d2).total_seconds()
        runtime_p = runtime_d / runtime_d1.total_seconds()

        days_d1 = datetime.timedelta(days=self.max_days)
        days_d2 = datetime.timedelta(seconds=now - self.filter_last_reset)
        days_d = (days_d1 - days_d2).total_seconds()
        days_p = days_d / days_d1.total_seconds()
        
        self.filter_percent_r = max(min(runtime_p, days_p) * 100, 0)
        self.filter_expired = self.filter_percent_r <= 0
        
        if self.filter_expired:
            self.filter_runtime_r = 0
            self.filter_days_r = 0
        else:
            self.filter_runtime_r = max(runtime_d, 0)
            self.filter_days_r = max(days_d, 0)

    def _persist(self):
        try:
            with open(self.file, "w", newline="", encoding="utf-8") as f:
                csv_writer = csv.writer(f, delimiter=",")
                csv_writer.writerow([
                    "%f" % self.filter_last_reset,
                    "%f" % self.filter_runtime,
                    "%f" % self.filter_total_runtime,
                    "%d" % self.filter_reset_count
                ])
        except IOError as e:
            self._log_exception("%s %s" % (self.file, str(e)))
        except:
            self._log_exception("Unable to write to %s" % self.file)

    def _notify(self):
        self.gcode.respond_info(self._format_status())
        
        if not self.filter_expired:
            return
            
        if self.expiry_gcode is not None:
            try:
                self.gcode.run_script(self.expiry_gcode.render())
            except:
                self._log_exception("Error executing expiry gcode")
                        
        self.filter_last_notified = time.time()
            
    def _format_msg(self, msg, separator=" ", color=None):
        return self._colorize_msg(
            ("%s%s%s" % (self.pretty_name, separator, msg)), color
        )

    def _format_status(self, extended=False):
        extended_msg = ""
        if extended:
            extended_msg = (
                "\nTotal Runtime: %s Resets: %d" % (
                    self._format_runtime(self.filter_total_runtime),
                    self.filter_reset_count
                )
            )

        maintenance_msg = ""
        if self.filter_expired:
            maintenance_msg = self._colorize_msg(
                "\nNeeds maintenance!", color="warning"
            )
		
        return self._format_msg(
            "at %s\nRuntime: %s Days: %.01f%s%s" % (
                self._format_percent(self.filter_percent_r),
                self._format_runtime(self.filter_runtime_r),
                self.filter_days_r / SEC_PER_DAY,
                extended_msg,
                maintenance_msg
            ),
            separator=" "
        )

    def _format_percent(self, percent):
        color = "success"
        if percent <= 10.0:
            color = "error"
        elif percent <= 25.0:
            color = "error"
            
        return self._colorize_msg(
            "%.01f%%" % percent, color
        )
        
    def _format_runtime(self, runtime):
        return (
            "%02d:%02d" % (
                math.floor(runtime / SEC_PER_HOUR),
                (runtime % SEC_PER_HOUR) / SEC_PER_MIN
            )
        )

    def _colorize_msg(self, msg, color):
        if color in COLORS:
            return (
                "<span class=%s--text>%s</span>" % (
                    color,
                    msg
                )
            )
        return msg
        
    def _log_info(self, msg):
        logging.info(self._format_msg(msg))

    def _log_exception(self, msg):
        formatted_msg = self._format_msg(msg)
        logging.exception(formatted_msg)
        raise self.printer.command_error(formatted_msg)

    def get_status(self, eventtime):
        return {
            "filter_last_active": self.filter_last_active,
            "filter_last_notified": self.filter_last_notified,
            "filter_last_reset": self.filter_last_reset,
            "filter_runtime": self.filter_runtime,
            "filter_total_runtime": self.filter_total_runtime,
            "filter_reset_count": self.filter_reset_count,
            "filter_active": self.filter_active,
            "filter_expired": self.filter_expired,
            "filter_percent_r": self.filter_percent_r,
            "filter_runtime_r": self.filter_runtime_r,
            "filter_days_r": self.filter_days_r
        }
        
    def cmd_FILTER_STATS(self, gcmd):
        self._update()
        
        gcmd.respond_info(
            self._format_status(
                extended=gcmd.get_int("EXTENDED", 0) == 1
            )
        )
        
    def cmd_RESET_FILTER(self, gcmd):
        if self.filter_active:
            gcmd.respond_info(
                self._format_msg("can't be reset while active!", color="error")
            )
        else:
            self.filter_last_reset = time.time()
            self.filter_runtime = 0.0
            self.filter_reset_count += 1
            self._update()
            
            gcmd.respond_info(
                self._format_msg("reset!", color="success")
            )
        
def load_config_prefix(config):
    return FilterMonitor(config)
