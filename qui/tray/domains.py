#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,import-error
''' A menu listing domains '''
import asyncio
import subprocess
import sys
import os
import traceback

import qubesadmin
import qubesadmin.events

from qubesadmin import exc
from html import escape

import qui.decorators
from qui.tutorial import QubesDomainTrayTutorialExtension
import qubes_tutorial.extensions
import gi  # isort:skip
gi.require_version('Gtk', '3.0')  # isort:skip
from gi.repository import Gio, Gtk, GObject  # isort:skip

import gbulb
gbulb.install()

import gettext
t = gettext.translation("desktop-linux-manager", fallback=True)
_ = t.gettext

STATE_DICTIONARY = {
    'domain-pre-start': 'Transient',
    'domain-start': 'Running',
    'domain-start-failed': 'Halted',
    'domain-paused': 'Paused',
    'domain-unpaused': 'Running',
    'domain-shutdown': 'Halted',
    'domain-pre-shutdown': 'Transient',
    'domain-shutdown-failed': 'Running'
}


class IconCache:
    def __init__(self):
        self.icon_files = {
            'pause': 'media-playback-pause',
            'terminal': 'utilities-terminal',
            'preferences': 'preferences-system',
            'kill': 'media-record',
            'shutdown': 'media-playback-stop',
            'unpause': 'media-playback-start',
            'files': 'system-file-manager',
            'restart': 'edit-redo'
        }
        self.icons = {}

    def get_icon(self, icon_name):
        if icon_name in self.icons.keys():
            icon = self.icons[icon_name]
        else:
            icon = Gtk.IconTheme.get_default().load_icon(
                self.icon_files[icon_name], 16, 0)
            self.icons[icon_name] = icon
        return icon


def show_error(title, text):
    dialog = Gtk.MessageDialog(
        None, 0, Gtk.MessageType.ERROR, Gtk.ButtonsType.OK)
    dialog.set_title(title)
    dialog.set_markup(text)
    dialog.connect("response", lambda *x: dialog.destroy())
    dialog.show()


class PauseItem(Gtk.ImageMenuItem):
    ''' Shutdown menu Item. When activated pauses the domain. '''

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('pause'))

        self.set_image(img)
        self.set_label(_('Emergency pause'))

        self.connect('activate', self.perform_pause)

    def perform_pause(self, *_args, **_kwargs):
        try:
            self.vm.pause()
        except exc.QubesException as ex:
            show_error(_("Error pausing qube"),
                       _("The following error occurred while "
                       "attempting to pause qube {0}:\n{1}").format(
                           self.vm.name, str(ex)))


class UnpauseItem(Gtk.ImageMenuItem):
    ''' Unpause menu Item. When activated unpauses the domain. '''

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('unpause'))

        self.set_image(img)
        self.set_label(_('Unpause'))

        self.connect('activate', self.perform_unpause)

    def perform_unpause(self, *_args, **_kwargs):
        try:
            self.vm.unpause()
        except exc.QubesException as ex:
            show_error(_("Error unpausing qube"),
                       _("The following error occurred while attempting "
                       "to unpause qube {0}:\n{1}").format(
                           self.vm.name, str(ex)))


class ShutdownItem(Gtk.ImageMenuItem):
    ''' Shutdown menu Item. When activated shutdowns the domain. '''

    def __init__(self, vm, app, icon_cache):
        super().__init__()
        self.vm = vm
        self.app = app

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('shutdown'))

        self.set_image(img)
        self.set_label(_('Shutdown'))

        self.connect('activate', self.perform_shutdown)

    def perform_shutdown(self, *_args, **_kwargs):
        try:
            self.vm.shutdown()
        except exc.QubesException as ex:
            show_error(_("Error shutting down qube"),
                       _("The following error occurred while attempting to "
                       "shut down qube {0}:\n{1}").format(
                           self.vm.name, str(ex)))


class RestartItem(Gtk.ImageMenuItem):
    ''' Restart menu Item. When activated shutdowns the domain and
    then starts it again. '''

    def __init__(self, vm, app, icon_cache):
        super().__init__()
        self.vm = vm
        self.app = app

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('restart'))

        self.set_image(img)
        self.set_label(_('Restart'))
        self.restart_thread = None

        self.connect('activate', self.restart)

    def restart(self, *_args, **_kwargs):
        asyncio.ensure_future(self.perform_restart())

    async def perform_restart(self):
        try:
            self.vm.shutdown()
            while self.vm.is_running():
                await asyncio.sleep(1)
            proc = await asyncio.create_subprocess_exec(
                'qvm-start', self.vm.name, stderr=subprocess.PIPE)
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise exc.QubesException(stderr)
        except exc.QubesException as ex:
            show_error(_("Error restarting qube"),
                       _("The following error occurred while attempting to "
                       "restart qube {0}:\n{1}").format(
                           self.vm.name, str(ex)))


class KillItem(Gtk.ImageMenuItem):
    ''' Kill domain menu Item. When activated kills the domain. '''

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('kill'))

        self.set_image(img)
        self.set_label(_('Kill'))

        self.connect('activate', self.perform_kill)

    def perform_kill(self, *_args, **_kwargs):
        try:
            self.vm.kill()
        except exc.QubesException as ex:
            show_error(_("Error shutting down qube"),
                       _("The following error occurred while attempting to shut"
                       "down qube {0}:\n{1}").format(self.vm.name, str(ex)))


class PreferencesItem(Gtk.ImageMenuItem):
    ''' Preferences menu Item. When activated shows preferences dialog '''

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('preferences'))

        self.set_image(img)
        self.set_label(_('Settings'))

        self.connect('activate', self.launch_preferences_dialog)

    def launch_preferences_dialog(self, _item):
        subprocess.Popen(['qubes-vm-settings', self.vm.name])


class LogItem(Gtk.ImageMenuItem):
    def __init__(self, name, path):
        super().__init__()
        self.path = path

        img = Gtk.Image.new_from_file(
            "/usr/share/icons/HighContrast/16x16/apps/logviewer.png")

        self.set_image(img)
        self.set_label(name)

        self.connect('activate', self.launch_log_viewer)

    def launch_log_viewer(self, *_args, **_kwargs):
        subprocess.Popen(['qubes-log-viewer', self.path])


class RunTerminalItem(Gtk.ImageMenuItem):
    ''' Run Terminal menu Item. When activated runs a terminal emulator. '''
    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        img = Gtk.Image.new_from_pixbuf(icon_cache.get_icon('terminal'))

        self.set_image(img)
        self.set_label(_('Run Terminal'))

        self.connect('activate', self.run_terminal)

    def run_terminal(self, _item):
        try:
            self.vm.run_service('qubes.StartApp+qubes-run-terminal')
        except exc.QubesException as ex:
            show_error(_("Error starting terminal"),
                       _("The following error occurred while attempting to "
                       "run terminal {0}:\n{1}").format(self.vm.name, str(ex)))


class OpenFileManagerItem(Gtk.ImageMenuItem):
    """Attempts to open a file manager in the VM. If fails, displays an
    error message."""

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        img = Gtk.Image.new_from_pixbuf(
            icon_cache.get_icon('files'))

        self.set_image(img)
        self.set_label(_('Open File Manager'))

        self.connect('activate', self.open_file_manager)

    def open_file_manager(self, _item):
        try:
            self.vm.run_service('qubes.StartApp+qubes-open-file-manager')
        except exc.QubesException as ex:
            show_error(_("Error opening file manager"),
                       _("The following error occurred while attempting to "
                       "open file manager {0}:\n{1}").format(
                           self.vm.name, str(ex)))


class StartedMenu(Gtk.Menu):
    ''' The sub-menu for a started domain'''

    def __init__(self, vm, app, icon_cache):
        super().__init__()
        self.vm = vm
        self.app = app

        self.add(OpenFileManagerItem(self.vm, icon_cache))
        self.add(RunTerminalItem(self.vm, icon_cache))
        self.add(PreferencesItem(self.vm, icon_cache))
        self.add(PauseItem(self.vm, icon_cache))
        self.add(ShutdownItem(self.vm, self.app, icon_cache))
        if self.vm.klass != 'DispVM' or not self.vm.auto_cleanup:
            self.add(RestartItem(self.vm, self.app, icon_cache))

        self.show_all()


class PausedMenu(Gtk.Menu):
    ''' The sub-menu for a paused domain'''

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        self.add(PreferencesItem(self.vm, icon_cache))
        self.add(UnpauseItem(self.vm, icon_cache))
        self.add(KillItem(self.vm, icon_cache))

        self.show_all()


class DebugMenu(Gtk.Menu):
    ''' Sub-menu providing multiple MenuItem for domain logs. '''

    def __init__(self, vm, icon_cache):
        super().__init__()
        self.vm = vm

        self.add(PreferencesItem(self.vm, icon_cache))

        logs = [
            (_("Console Log"),
             "/var/log/xen/console/guest-" + vm.name + ".log"),
            (_("QEMU Console Log"),
             "/var/log/xen/console/guest-" + vm.name + "-dm.log"),
            ]

        for name, path in logs:
            if os.path.isfile(path):
                self.add(LogItem(name, path))

        self.add(KillItem(self.vm, icon_cache))

        self.show_all()


def run_manager(_item):
    subprocess.Popen(['qubes-qube-manager'])


class QubesManagerItem(Gtk.ImageMenuItem):
    def __init__(self):
        super().__init__()

        self.set_image(Gtk.Image.new_from_icon_name('qubes-logo-icon',
                                                    Gtk.IconSize.MENU))

        self.set_label(_('Open Qube Manager'))

        self.connect('activate', run_manager)

        self.show_all()


class DomainMenuItem(Gtk.ImageMenuItem):
    def __init__(self, vm, app, icon_cache, state=None):
        super().__init__()
        self.vm = vm
        self.app = app
        self.icon_cache = icon_cache
        # set vm := None to make this output headers.
        # Header menu item reuses the domain menu item code
        #   so headers are aligned with the columns.

        self.decorator = qui.decorators.DomainDecorator(vm)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        # hbox.set_homogeneous(True)

        namebox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.name = self.decorator.name()
        namebox.pack_start(self.name, True, True, 0)
        self.spinner = Gtk.Spinner()
        namebox.pack_start(self.spinner, False, True, 0)

        hbox.pack_start(namebox, True, True, 0)

        mem_cpu_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        # mem_cpu_box.set_homogeneous(True)
        self.memory = self.decorator.memory()
        mem_cpu_box.pack_start(self.memory, False, True, 0)
        self.cpu = self.decorator.cpu()
        mem_cpu_box.pack_start(self.cpu, False, True, 0)

        hbox.pack_start(mem_cpu_box, False, True, 0)

        self.add(hbox)

        if self.vm is None:  # if header
            self.set_reserve_indicator(True)  # align with submenu triangles
            self.cpu.update_state(header=True)
            self.memory.update_state(header=True)
            self.show_all()  # header should always be visible
        elif self.vm.klass == 'AdminVM':  # no submenu for AdminVM
            self.set_reserve_indicator(True)  # align with submenu triangles
        else:
            if not state:
                self.update_state(self.vm.get_power_state())
            else:
                self.update_state(state)
            self.set_label_icon()

    def set_label_icon(self):
        self.set_image(self.decorator.icon())

    def _set_submenu(self, state):
        if state == 'Running':
            submenu = StartedMenu(self.vm, self.app, self.icon_cache)
        elif state == 'Paused':
            submenu = PausedMenu(self.vm, self.icon_cache)
        else:
            submenu = DebugMenu(self.vm, self.icon_cache)
        # This is a workaround for a bug in Gtk which occurs when a
        # submenu is replaced while it is open.
        # see https://gitlab.gnome.org/GNOME/gtk/issues/885
        current_submenu = self.get_submenu()
        if current_submenu:
            current_submenu.grab_remove()
        self.set_submenu(submenu)

    def show_spinner(self):
        self.spinner.start()
        self.spinner.set_no_show_all(False)
        self.spinner.show()
        self.show_all()

    def hide_spinner(self):
        self.spinner.stop()
        self.spinner.set_no_show_all(True)
        self.spinner.hide()

    def update_state(self, state):
        vm_klass = getattr(self.vm, 'klass', None)

        if not self.vm or vm_klass == 'AdminVM':
            # it's a header or an AdminVM, no need to do anything
            return

        if not vm_klass:
            # it's a DispVM in a very fragile state; just make sure to add
            # correct submenu
            self._set_submenu(state)
            return

        # if VM is not running, hide it
        if state == 'Halted':
            self.hide()
            return

        if state in ['Running', 'Paused']:
            self.hide_spinner()
        else:
            self.show_spinner()
        colormap = {'Paused': 'grey', 'Crashed': 'red', 'Transient': 'red'}
        if state in colormap:
            self.name.label.set_markup('<span color=\'{}\'>{}</span>'.format(
                colormap[state], self.vm.name))
        else:
            self.name.label.set_label(self.vm.name)

        self._set_submenu(state)

    def update_stats(self, memory_kb, cpu_usage):
        self.memory.update_state(int(memory_kb))
        self.cpu.update_state(int(cpu_usage))


class DomainTray(Gtk.Application):
    ''' A tray icon application listing all but halted domains. ” '''

    def __init__(self, app_name, qapp, dispatcher, stats_dispatcher):
        super().__init__()
        self.qapp = qapp
        self.dispatcher = dispatcher
        self.stats_dispatcher = stats_dispatcher

        # FIXME add option to enable via arg --tutorial
        QubesDomainTrayTutorialExtension(self)

        self.widget_icon = Gtk.StatusIcon()
        self.widget_icon.set_from_icon_name('qui-domains')
        self.widget_icon.connect('button-press-event', self.show_menu)
        self.widget_icon.set_tooltip_markup(
            _('<b>Qubes Domains</b>\nView and manage running domains.'))

        self.tray_menu = Gtk.Menu()

        self.icon_cache = IconCache()

        self.menu_items = {}

        self.unpause_all_action = Gio.SimpleAction.new('do-unpause-all', None)
        self.unpause_all_action.connect('activate', self.do_unpause_all)
        self.add_action(self.unpause_all_action)
        self.pause_notification_out = False

        # add refreshing tooltips with storage info
        GObject.timeout_add_seconds(120, self.refresh_tooltips)

        self.register_events()
        self.set_application_id(app_name)
        self.register()  # register Gtk Application

    def register_events(self):
        self.dispatcher.add_handler('domain-pre-start', self.update_domain_item)
        self.dispatcher.add_handler('domain-start', self.update_domain_item)
        self.dispatcher.add_handler('domain-start-failed',
                                    self.update_domain_item)
        self.dispatcher.add_handler('domain-paused', self.update_domain_item)
        self.dispatcher.add_handler('domain-unpaused', self.update_domain_item)
        self.dispatcher.add_handler('domain-shutdown', self.update_domain_item)
        self.dispatcher.add_handler('domain-pre-shutdown',
                                    self.update_domain_item)
        self.dispatcher.add_handler('domain-shutdown-failed',
                                    self.update_domain_item)

        self.dispatcher.add_handler('domain-add', self.add_domain_item)
        self.dispatcher.add_handler('domain-delete', self.remove_domain_item)

        self.dispatcher.add_handler('domain-pre-start', self.emit_notification)
        self.dispatcher.add_handler('domain-start', self.emit_notification)
        self.dispatcher.add_handler('domain-start-failed',
                                    self.emit_notification)
        self.dispatcher.add_handler('domain-pre-shutdown',
                                    self.emit_notification)
        self.dispatcher.add_handler('domain-shutdown', self.emit_notification)
        self.dispatcher.add_handler('domain-shutdown-failed',
                                    self.emit_notification)

        self.dispatcher.add_handler('domain-start', self.check_pause_notify)
        self.dispatcher.add_handler('domain-paused', self.check_pause_notify)
        self.dispatcher.add_handler('domain-unpaused', self.check_pause_notify)
        self.dispatcher.add_handler('domain-shutdown', self.check_pause_notify)

        self.dispatcher.add_handler('domain-feature-set:updates-available',
                                    self.feature_change)
        self.dispatcher.add_handler('domain-feature-delete:updates-available',
                                    self.feature_change)
        self.dispatcher.add_handler('property-set:netvm', self.property_change)
        self.dispatcher.add_handler('property-set:label', self.property_change)

        self.stats_dispatcher.add_handler('vm-stats', self.update_stats)

    @qubes_tutorial.extensions.register("qubes_domains:open")
    def show_menu(self, _unused, _event):
        self.tray_menu.popup_at_pointer(None)  # None means current event

    def show_tutorial_path(self, vm_name, action_name):
        submenu_class_map = {
            "pause":    PauseItem,
            "unpause":  UnpauseItem,
            "shutdown": ShutdownItem,
            "restart": RestartItem,
            "kill": KillItem,
            "preferences": PreferencesItem,
            "log": LogItem,
            "run-terminal": RunTerminalItem,
            "open-file-manager": OpenFileManagerItem
        }
        action_item_class = submenu_class_map[action_name]
        # highlight qube
        for domain_item in self.tray_menu.get_children():
            vm = getattr(domain_item, "vm", None)
            if vm is None: # ignore separator items
                continue
            if vm.name == vm_name:
                qubes_tutorial.extensions.widget_highlight(domain_item)

                # highlight action (e.g. "Shutdown", "Open File Manager", etc.)
                submenu = domain_item.get_submenu()
                if submenu is None:
                    continue
                for submenu_item in submenu.get_children():
                    if isinstance(submenu_item, action_item_class):
                        qubes_tutorial.extensions.widget_highlight(submenu_item)

    def hide_tutorial_path(self):
        for domain_item in self.tray_menu.get_children():
            vm = getattr(domain_item, "vm", None)
            if vm is None: # ignore separator items
                continue
            qubes_tutorial.extensions.widget_highlight_remove(domain_item)
            submenu = domain_item.get_submenu()
            if submenu is None:
                continue
            for submenu_item in submenu.get_children():
                qubes_tutorial.extensions.widget_highlight_remove(submenu_item)

    def emit_notification(self, vm, event, **kwargs):
        notification = Gio.Notification.new(_(
            "Qube Status: {}"). format(vm.name))
        notification.set_priority(Gio.NotificationPriority.NORMAL)

        if event == 'domain-start-failed':
            notification.set_body(_('Qube {} has failed to start: {}').format(
                vm.name, kwargs['reason']))
            notification.set_priority(Gio.NotificationPriority.HIGH)
            notification.set_icon(
                Gio.ThemedIcon.new('dialog-warning'))
        elif event == 'domain-pre-start':
            notification.set_body(_('Qube {} is starting.').format(vm.name))
        elif event == 'domain-start':
            notification.set_body(_('Qube {} has started.').format(vm.name))
        elif event == 'domain-pre-shutdown':
            notification.set_body(
                _('Qube {} is attempting to shut down.').format(vm.name))
        elif event == 'domain-shutdown':
            notification.set_body(_('Qube {} has shut down.').format(vm.name))
        elif event == 'domain-shutdown-failed':
            notification.set_body(
                _('Qube {} failed to shut down: {}').format(
                    vm.name, kwargs['reason']))
            notification.set_priority(Gio.NotificationPriority.HIGH)
            notification.set_icon(
                Gio.ThemedIcon.new('dialog-warning'))
        else:
            return
        self.send_notification(None, notification)

    def emit_paused_notification(self):
        if not self.pause_notification_out:
            notification = Gio.Notification.new(_("Your qubes have been "
                "paused!"))
            notification.set_body(_(
                "All your qubes are currently paused. If this was an accident, "
                "simply click \"Unpause All\" to unpause them. Otherwise, "
                "you can unpause individual qubes via the Qubes Domains "
                "tray widget."))
            notification.set_icon(
                Gio.ThemedIcon.new('dialog-warning'))
            notification.add_button(_('Unpause All'), 'app.do-unpause-all')
            notification.set_priority(Gio.NotificationPriority.HIGH)
            self.send_notification('vms-paused', notification)
            self.pause_notification_out = True

    def withdraw_paused_notification(self):
        if self.pause_notification_out:
            self.withdraw_notification('vms-paused')
            self.pause_notification_out = False

    def do_unpause_all(self, _vm, *_args, **_kwargs):
        for vm_name in self.menu_items:
            try:
                self.qapp.domains[vm_name].unpause()
            except exc.QubesException:
                # we may not have permission to do that
                pass

    def check_pause_notify(self, _vm, _event, **_kwargs):
        if self.have_running_and_all_are_paused():
            self.emit_paused_notification()
        else:
            self.withdraw_paused_notification()

    def have_running_and_all_are_paused(self):
        found_paused = False
        for vm in self.qapp.domains:
            if vm.klass != 'AdminVM':
                if vm.is_running():
                    if vm.is_paused():
                        # a running that is paused
                        found_paused = True
                    else:
                        # found running that wasn't paused
                        return False
        return found_paused

    def add_domain_item(self, _submitter, event, vm, **_kwargs):
        """Add a DomainMenuItem to menu; if event is None, this was fired
         manually (mot due to domain-add event, and it is assumed the menu items
         are created in alphabetical order. Otherwise, this method will
         attempt to sort menu items correctly."""
        # check if it already exists
        try:
            vm = self.qapp.domains[str(vm)]
        except KeyError:
            # the VM was not created successfully or was deleted before the
            # event was fully handled
            return
        if vm in self.menu_items:
            return

        state = STATE_DICTIONARY.get(event)
        if not state:
            try:
                state = vm.get_power_state()
            except exc.QubesException:
                # VM might have been already destroyed
                if vm not in self.qapp.domains:
                    return
                # or we might not have permission to access its power state
                state = 'Halted'

        domain_item = DomainMenuItem(vm, self, self.icon_cache, state=state)
        if not event:  # menu item creation at widget start; we can assume
            # menu items are created in alphabetical order
            self.tray_menu.add(domain_item)
        else:
            position = 0
            for i in self.tray_menu:  # pylint: disable=not-an-iterable
                if not hasattr(i, 'vm'):  # we reached the end
                    break
                if not i.vm:  # header should be skipper
                    position += 1
                    continue
                if i.vm.klass == 'AdminVM':
                    # AdminVM(s) should be skipped
                    position += 1
                    continue
                if i.vm.name > vm.name:
                    # we reached correct alphabetical placement for the VM
                    break
                position += 1
            self.tray_menu.insert(domain_item, position)
        self.menu_items[vm] = domain_item

    def property_change(self, vm, event, *_args, **_kwargs):
        if vm not in self.menu_items:
            return
        if event == 'property-set:netvm':
            self.menu_items[vm].name.update_tooltip(netvm_changed=True)
        elif event == 'property-set:label':
            self.menu_items[vm].set_label_icon()

    def feature_change(self, vm, *_args, **_kwargs):
        if vm not in self.menu_items:
            return
        self.menu_items[vm].name.update_updateable()

    def refresh_tooltips(self):
        for item in self.menu_items.values():
            if item.vm and item.is_visible():
                try:
                    item.name.update_tooltip(storage_changed=True)
                except Exception:  # pylint: disable=broad-except
                    pass

    def remove_domain_item(self, _submitter, _event, vm, **_kwargs):
        if vm not in self.menu_items:
            return
        vm_widget = self.menu_items[vm]
        self.tray_menu.remove(vm_widget)
        del self.menu_items[vm]

    def handle_domain_shutdown(self, vm):
        try:
            if getattr(vm, 'klass', None) == 'TemplateVM':
                for menu_item in self.menu_items.values():
                    try:
                        if not menu_item.vm.is_running():
                            # A VM based on this template can only be
                            # outdated if the VM is currently running.
                            continue
                    except exc.QubesPropertyAccessError:
                        continue
                    if getattr(menu_item.vm, 'template', None) == vm and \
                            any(vol.is_outdated()
                                for vol in menu_item.vm.volumes.values()):
                        menu_item.name.update_outdated(True)
        except exc.QubesVMNotFoundError:
            # attribute not available anymore as VM was removed
            # in the meantime
            pass

    def update_domain_item(self, vm, event, **kwargs):
        ''' Update the menu item with the started menu for
        the specified vm in the tray'''
        try:
            item = self.menu_items[vm]
        except exc.QubesPropertyAccessError:
            print(_("Unexpected property access error"))  # req by @marmarek
            traceback.print_exc()
            self.remove_domain_item(vm, event, **kwargs)
            return
        except KeyError:
            self.add_domain_item(None, event, vm)
            if not vm in self.menu_items:
                # VM not added - already removed?
                return
            item = self.menu_items[vm]

        if event in STATE_DICTIONARY:
            state = STATE_DICTIONARY[event]
        else:
            try:
                state = vm.get_power_state()
            except Exception: # pylint: disable=broad-except
                # it's a fragile DispVM
                state = "Transient"

        item.update_state(state)

        if event == 'domain-shutdown':
            self.handle_domain_shutdown(vm)
            # if the VM was shut down, it is no longer outdated
            item.name.update_outdated(False)

        if event in ('domain-start', 'domain-pre-start'):
            # A newly started VM should not be outdated.
            item.name.update_outdated(False)
            item.show_all()
        if event == 'domain-shutdown':
            item.hide()

    def update_stats(self, vm, _event, **kwargs):
        if vm not in self.menu_items:
            return
        self.menu_items[vm].update_stats(
            kwargs['memory_kb'], kwargs['cpu_usage'])

    def initialize_menu(self):
        self.tray_menu.add(DomainMenuItem(None, self, self.icon_cache))

        # Add AdminVMS
        for vm in sorted([vm for vm in self.qapp.domains
                          if vm.klass == "AdminVM"]):
            self.add_domain_item(None, None, vm)

        # and the rest of them
        for vm in sorted([vm for vm in self.qapp.domains
                          if vm.klass != 'AdminVM']):
            self.add_domain_item(None, None, vm)

        for item in self.menu_items.values():
            try:
                if item.vm and item.vm.is_running():
                    item.name.update_tooltip(storage_changed=True)
                    item.show_all()
                else:
                    item.hide()
            except exc.QubesPropertyAccessError:
                item.hide()

        self.tray_menu.add(Gtk.SeparatorMenuItem())
        self.tray_menu.add(QubesManagerItem())

        self.connect('shutdown', self._disconnect_signals)

    def run(self):  # pylint: disable=arguments-differ
        self.initialize_menu()

    def _disconnect_signals(self, _event):
        self.dispatcher.remove_handler('domain-pre-start',
                                       self.update_domain_item)
        self.dispatcher.remove_handler('domain-start', self.update_domain_item)
        self.dispatcher.remove_handler('domain-start-failed',
                                       self.update_domain_item)
        self.dispatcher.remove_handler('domain-paused', self.update_domain_item)
        self.dispatcher.remove_handler('domain-unpaused',
                                       self.update_domain_item)
        self.dispatcher.remove_handler('domain-shutdown',
                                       self.update_domain_item)
        self.dispatcher.remove_handler('domain-pre-shutdown',
                                       self.update_domain_item)
        self.dispatcher.remove_handler('domain-shutdown-failed',
                                       self.update_domain_item)

        self.dispatcher.remove_handler('domain-add', self.add_domain_item)
        self.dispatcher.remove_handler('domain-delete', self.remove_domain_item)

        self.dispatcher.remove_handler('domain-pre-start',
                                       self.emit_notification)
        self.dispatcher.remove_handler('domain-start', self.emit_notification)
        self.dispatcher.remove_handler('domain-start-failed',
                                       self.emit_notification)
        self.dispatcher.remove_handler('domain-pre-shutdown',
                                       self.emit_notification)
        self.dispatcher.remove_handler('domain-shutdown',
                                       self.emit_notification)
        self.dispatcher.remove_handler('domain-shutdown-failed',
                                       self.emit_notification)

        self.dispatcher.remove_handler('domain-start', self.check_pause_notify)
        self.dispatcher.remove_handler('domain-paused', self.check_pause_notify)
        self.dispatcher.remove_handler('domain-unpaused',
                                       self.check_pause_notify)
        self.dispatcher.remove_handler('domain-shutdown',
                                       self.check_pause_notify)

        self.dispatcher.remove_handler('domain-feature-set:updates-available',
                                       self.feature_change)
        self.dispatcher.remove_handler(
            'domain-feature-delete:updates-available', self.feature_change)
        self.dispatcher.remove_handler('property-set:netvm',
                                       self.property_change)
        self.dispatcher.remove_handler('property-set:label',
                                       self.property_change)

        self.stats_dispatcher.remove_handler('vm-stats', self.update_stats)


def main():
    ''' main function '''
    qapp = qubesadmin.Qubes()
    dispatcher = qubesadmin.events.EventsDispatcher(qapp)
    stats_dispatcher = qubesadmin.events.EventsDispatcher(
        qapp, api_method='admin.vm.Stats')
    app = DomainTray(
        'org.qubes.qui.tray.Domains', qapp, dispatcher, stats_dispatcher)
    app.run()

    loop = asyncio.get_event_loop()
    tasks = [
        asyncio.ensure_future(dispatcher.listen_for_events()),
        asyncio.ensure_future(stats_dispatcher.listen_for_events()),
    ]

    done, _unused = loop.run_until_complete(asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION))

    exit_code = 0

    for d in done:  # pylint: disable=invalid-name
        try:
            d.result()
        except Exception as _ex:  # pylint: disable=broad-except
            exc_type, exc_value = sys.exc_info()[:2]
            dialog = Gtk.MessageDialog(
                None, 0, Gtk.MessageType.ERROR, Gtk.ButtonsType.OK)
            dialog.set_title(_("Houston, we have a problem..."))
            dialog.set_markup(_(
                "<b>Whoops. A critical error in Qubes Domains has occurred.</b>"
                " This is most likely a bug in the widget. Qubes Domains"
                " will restart itself."))
            exc_description = "\n<b>{}</b>: {}\n{}".format(
                   exc_type.__name__, exc_value, traceback.format_exc(limit=10)
                )
            dialog.format_secondary_markup(escape(exc_description))
            dialog.run()
            exit_code = 1
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
