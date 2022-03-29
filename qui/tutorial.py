import subprocess
from gi.repository import GLib

from qubes_tutorial.extensions import GtkTutorialExtension

class QubesDomainTrayTutorialExtension(GtkTutorialExtension):

    def __init__(self, app):
        super().__init__("qubes_domains")
        self.app = app

    def do_show_tutorial_path(self, vm_name, action_name):
        """
        Highlights the path to an action in the qubes-domains widget, showing
        the user a path to click it.
        """
        GLib.idle_add(self.app.show_tutorial_path, vm_name, action_name)
        return "highlighted successfully {}, {}".format(vm_name, action_name)

    def do_hide_tutorial_path(self):
        """
        Removes tutorial highlights.
        """
        GLib.idle_add(self.app.hide_tutorial_path)
        return "removed highlights"
