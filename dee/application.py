import os
import glob
import sys
import logging
import subprocess
import shlex
import tempfile
from gi.repository import GObject, Gio, Gdk, GdkPixbuf, Gtk, Pango
from gi.repository import GtkSource
from dee.entry import Entry
from xdg.DesktopEntry import  ParsingError, ValidationError

from xdg.BaseDirectory import xdg_data_dirs

APP_NAME = "Desktop Entry Editor"
APP_DESCRIPTION = "A desktop entry (application launcher) editor\nbased on the freedesktop.org specifications."
APP_VERSION = "0.1"
DATA_DIR = "data"
# XDG_DATA_DIR
SETTINGS_SCHEMA = "apps.desktop-entry-editor"

logging.basicConfig()
LOG_LEVEL = logging.DEBUG
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

class Application(object):
    
    STATE_NORMAL = 0
    STATE_LOADING = 1    
    
    SOURCE_TAB = 2
    ADVANCED_TAB = 1
    
    ALL_KEYS = (
        ('Type', 'This specification defines 3 types of desktop entries: Application (type 1), Link (type 2) and Directory (type 3). To allow the addition of new types in the future, implementations should ignore desktop entries with an unknown type.', str),
        ('Version', 'Version of the Desktop Entry Specification that the desktop entry conforms with. Entries that confirm with this version of the specification should use 1.0. Note that the version field is not required to be present.', str),
        ('Name', 'Specific name of the application, for example "Mozilla".', str),
        ('GenericName', 'Generic name of the application, for example "Web Browser".', str),
        ('NoDisplay', 'NoDisplay means "this application exists, but don\'t display it in the menus". This can be useful to e.g. associate this application with MIME types, so that it gets launched from a file manager (or other apps), without having a menu entry for it (there are tons of good reasons for this, including e.g. the netscape -remote, or kfmclient openURL kind of stuff).', bool),
        ('Comment', 'Tooltip for the entry, for example "View sites on the Internet". The value should not be redundant with the values of Name and GenericName.', str),
        ('Icon','Icon to display in file manager, menus, etc. If the name is an absolute path, the given file will be used. If the name is not an absolute path, the algorithm described in the Icon Theme Specification will be used to locate the icon.', str),
        ('Hidden', 'Hidden should have been called Deleted. It means the user deleted (at his level) something that was present (at an upper level, e.g. in the system dirs). It\'s strictly equivalent to the .desktop file not existing at all, as far as that user is concerned. This can also be used to "uninstall" existing files (e.g. due to a renaming) - by letting make install install a file with Hidden=true in it.', bool),
        ('OnlyShowIn','A list of strings identifying the environments that should display/not display a given desktop entry. Only one of these keys, either OnlyShowIn or NotShowIn, may appear in a group (for possible values see the Desktop Menu Specification).', str),
        ('NotShowIn','A list of strings identifying the environments that should display/not display a given desktop entry. Only one of these keys, either OnlyShowIn or NotShowIn, may appear in a group (for possible values see the Desktop Menu Specification).', str),
        ('TryExec','Path to an executable file on disk used to determine if the program is actually installed. If the path is not an absolute path, the file is looked up in the $PATH environment variable. If the file is not present or if it is not executable, the entry may be ignored (not be used in menus, for example).',str),
        ('Exec','Program to execute, possibly with arguments.',str),
        ('Path','If entry is of type Application, the working directory to run the program in.',str),
        ('Terminal','Whether the program runs in a terminal window.',bool),
        ('MimeType','The MIME type(s) supported by this application.',str),
        ('Categories','Categories in which the entry should be shown in a menu (for possible values see the Desktop Menu Specification).',str),
        ('StartupNotify','If true, it is KNOWN that the application will send a "remove" message when started with the DESKTOP_STARTUP_ID environment variable set. If false, it is KNOWN that the application does not work with startup notification at all (does not shown any window, breaks even when using StartupWMClass, etc.). If absent, a reasonable handling is up to implementations (assuming false, using StartupWMClass, etc.). (See the Startup Notification Protocol Specification for more details).',bool),
        ('StartupWMClass','If specified, it is known that the application will map at least one window with the given string as its WM class or WM name hint (see the Startup Notification Protocol Specification for more details).',str),
        ('URL','If entry is Link type, the URL to access.',str)
    )
    def close_file(self):
        """
        Close the currently open desktop entry file.
        """
        self._entry = None
        self._load_desktop_entry_ui()
        # TODO deselect tree view
        
    def error_dialog(self, message):
        """ Display a very basic error dialog. """
        logger.warn(message)
        dialog = Gtk.MessageDialog(self.window,
                                   Gtk.DialogFlags.MODAL | 
                                   Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                   Gtk.MessageType.ERROR, Gtk.ButtonsType.OK, 
                                   message)
        dialog.set_title("Error")
        dialog.run()
        dialog.destroy()
    
    def overwrite_existing_file_dialog(self, filename):
        """
        Prompt the user to overwrite an existing file.
        """
        if os.path.exists(filename):
            message = "A file named %s already exists.\nDo you want to replace it?" \
                % os.path.basename(filename)
            dialog = Gtk.MessageDialog(self.window,
                                       Gtk.DialogFlags.MODAL | 
                                       Gtk.DialogFlags.DESTROY_WITH_PARENT,
                                       Gtk.MessageType.QUESTION, Gtk.ButtonsType.YES_NO, 
                                       message)
            dialog.set_title('Overwrite Existing File?')
            r = dialog.run()
            dialog.destroy()
            
            if r == Gtk.ResponseType.YES:
                return True
            else:
                return False
                
        return True
        
    def _get_app_icon_pixbuf(self, size=None):
        """
        Get a new GdkPixbuf for the app's main icon rendered at size.
        """
        pixbuf_file = os.path.join(DATA_DIR, "icons", "scalable", "desktop-entry-editor.svg")
        if size:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(pixbuf_file, size, size, True)
        else:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(pixbuf_file)
        return pixbuf
        
    def __init__(self):
        """
        Build UI from Glade XML file found in DATA_DIR.
        """
        
        builder = Gtk.Builder()
        try:
            builder.add_from_file(os.path.join(DATA_DIR, "main_window.ui"))
        except Exception as e:
            sys.exit("Failed to load UI file: %s." % str(e))
        self.window = builder.get_object("main_window")
        # TODO use custom icon name (themed icon)
        self.window.set_icon(self._get_app_icon_pixbuf())
        self._notebook = builder.get_object("notebook")
        self._statusbar = builder.get_object("statusbar")
        self._statusbar_ctx = self._statusbar.get_context_id("Selected entry.")
        self._init_settings()
        self._init_treeview(builder)
        self._init_basic_tab(builder)
        self._init_advanced_tab(builder)
        self._init_source_tab(builder)
        
        # groups of widgets that share state (should have used GtkActions)
        self._save_widgets = (
            builder.get_object("save_button"),
            builder.get_object("save_menuitem")
        )
        self._open_file_widgets= (
            builder.get_object("close_menuitem"),
            builder.get_object("save_as_menuitem"),
            self._notebook,
        )
        
        builder.connect_signals(self)
        self._state = self.STATE_NORMAL
        self.close_file()
    
    def _init_settings(self):
        """
        Initialize a GSettings object and connect callbacks.
        """
        self._settings = Gio.Settings.new(SETTINGS_SCHEMA)
        self._settings.connect("changed::show-read-only-files", 
                               lambda settings,key: self._load_treeview())
        
    def _init_source_tab(self, builder):
        """
        Initialize a GtkSourceView to show the desktop entry in the 'Source' tab
        """
        scrolled_window = builder.get_object("source_scrolled_window")
        # why do I have to explicity create the buffer?
        self._sourceview = GtkSource.View.new_with_buffer(GtkSource.Buffer())
        buffer = self._sourceview.get_buffer()
        scrolled_window.add(self._sourceview)
        self._sourceview.set_show_line_numbers(True)
        font_desc = Pango.FontDescription("monospace 10") # TODO configurable
        self._sourceview.modify_font(font_desc)
        manager = GtkSource.LanguageManager().get_default()
        language = manager.get_language("ini")
        buffer.set_language(language)
        scrolled_window.show_all()
        
        
    def _init_treeview(self, builder):
        """
        Initialize the tree view's model and columns.
        """
        self._treeview = builder.get_object("treeview")
        # why doesn't button-press-event work when defined in Glade?
        self._treeview.connect("button-press-event", self.on_treeview_button_press_event)
        model = Gtk.ListStore(GdkPixbuf.Pixbuf,         # icon
                              GObject.TYPE_STRING,      # name
                              GObject.TYPE_STRING,      # desktop entry file
                              GObject.TYPE_STRING,      # tooltip
                              GObject.TYPE_STRING)      # markup
        model.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self._treeview.set_model(model)
        self._treeview.set_headers_visible(False)
        
        column = Gtk.TreeViewColumn("Launchers")
        cell = Gtk.CellRendererPixbuf()
        column.pack_start(cell, False)
        column.add_attribute(cell, "pixbuf", 0)
        cell = Gtk.CellRendererText()
        column.pack_start(cell, True)
        column.add_attribute(cell, "markup", 4)
        self._treeview.append_column(column)
        
        self._missing_pixbuf = self.window.render_icon_pixbuf(Gtk.STOCK_MISSING_IMAGE,
                                                              Gtk.IconSize.MENU)
    
    def _init_advanced_tab(self, builder):
        """
        Initialize the advanced tab with a treeview of key/values.
        """
        self._advanced_treeview = builder.get_object("advanced_treeview")
        treeview = self._advanced_treeview
        model = Gtk.ListStore(GObject.TYPE_STRING,      # key
                              GObject.TYPE_STRING,      # value (as string)
                              GObject.TYPE_STRING)      # tooltip
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        treeview.set_model(model)
        treeview.set_headers_visible(True)
        
        column = Gtk.TreeViewColumn("Key")
        cell = Gtk.CellRendererText()
        column.pack_start(cell, True)
        column.add_attribute(cell, "text", 0)
        treeview.append_column(column)
        
        column = Gtk.TreeViewColumn("Value")
        cell = Gtk.CellRendererText()
        column.pack_start(cell, True)
        column.add_attribute(cell, "text", 1)
        treeview.append_column(column)
        
    def _init_basic_tab(self, builder):
        """
        Initialize the the "Basic" tab with the minimum fields for a launcher.
        """
        self._type_combo = builder.get_object("type_combo")
        self._name_entry = builder.get_object("name_entry")
        self._icon_entry = builder.get_object("icon_entry")
        self._exec_entry = builder.get_object("exec_entry")
        self._terminal_checkbutton = builder.get_object("terminal_checkbutton")
        
        # populate type combo box
        model = Gtk.ListStore(GObject.TYPE_STRING)
        model.append(("Application",))
        model.append(("Directory",))
        model.append(("Link",))

        cell = Gtk.CellRendererText()
        self._type_combo.pack_start(cell, True)
        self._type_combo.add_attribute(cell, "text", 0)
        
        self._type_combo.set_model(model)
        self._type_combo.set_id_column(0)
        self._type_combo.set_active_id("Application")
    
    def _load_desktop_entry_ui(self):
        """
        Load the current Entry into the various widgets of the GUI.
        """
        self._state = self.STATE_LOADING
        entry = self._entry
        self._update_ui()
        if not entry:
            # clear all
            self._statusbar.pop(self._statusbar_ctx)
            self._sourceview.get_buffer().set_text("")
            self._type_combo.set_active_id("Application")
            self._name_entry.set_text("")
            self._icon_entry.set_text("")
            self._exec_entry.set_text("")
            self._terminal_checkbutton.set_active(False)
            [widget.set_sensitive(False) for widget in self._open_file_widgets]
            self._state = self.STATE_NORMAL
            return
            
        # statusbar
        self._statusbar.pop(self._statusbar_ctx)
        self._statusbar.push(self._statusbar_ctx, entry.filename)

        # populate basic tab
        self._type_combo.set_active_id(entry.getType())
        self._name_entry.set_text(entry.getName())
        self._icon_entry.set_text(entry.getIcon())
        self._exec_entry.set_text(entry.getExec())
        self._terminal_checkbutton.set_active(entry.getTerminal())

        # populate advanced tab

        # load file into source view
        self._update_source_tab()
            
        [widget.set_sensitive(True) for widget in self._open_file_widgets]
        self._state = self.STATE_NORMAL
        
    def _load_treeview(self):
        """
        Load the treeview with the .desktop entries found at path.
        """
        self._treeview.set_sensitive(False)
        model = self._treeview.get_model()
        model.clear()
        for path in xdg_data_dirs:
            path = os.path.join(path, "applications")
            logger.debug("Loading desktop entries from %s" % path)
            for desktop_file in glob.glob(os.path.join(path, "*.desktop")):
                try:
                    entry = Entry(desktop_file)
                except ParsingError, e:
                    logger.warn(e)
                    continue # skip entries with parse errors

                pixbuf = entry.getIconPixbuf(16)

                if entry.getGenericName():
                    tooltip = entry.getGenericName()
                else:
                    tooltip = entry.getName()
                
                if entry.isReadOnly():
                    if self._settings.get_boolean('show-read-only-files'):
                        markup = "<span color='#888888'>%s</span>" % entry.getName()
                    else:
                        continue # skip read-only per settings
                else:
                    markup = entry.getName()
                
                model.append((pixbuf, entry.getName(), desktop_file, tooltip, markup,))
        self._treeview.set_sensitive(True)
    
    def new_file(self):
        """
        Create a new, empty desktop entry.
        """
        old_entry = self._entry
        self._entry = Entry()
        filename = self.save_dialog()
        if filename:
            self._entry.new(filename)
            self._entry.set("Name", "Untitled")
            logger.debug(self._entry.getName())
            self.save_file(filename)
        else:
            self._entry = old_entry
    
    def on_type_combo_changed(self, combo, data=None):
        type_str = combo.get_model()[combo.get_active()][0]
        self._ui_value_changed("Type", type_str)
        
    def on_exec_entry_changed(self, entry, data=None):
        self._ui_value_changed("Exec", entry.get_text())
        
    def on_exec_entry_icon_press(self, entry, icon_pos, event, data=None):
        """
        Execute the command when the user presses the icon in the entry.
        """
        # TODO async? Wait for retval?
        if not self._entry:     
            return
        retval = subprocess.call(self._entry.getExec(), shell=True)
        logger.debug("Exited with code " + str(retval))
    
    def on_file_close_activate(self, menuitem, data=None):
        self.close_file()
    
    def on_file_new_activate(self, menuitem, data=None):
        self.new_file()
    
    def on_file_save_activate(self, menuitem, data=None):
        self.save_file(self._entry.filename)
    
    def on_help_about_activate(self, menuitem, data=None):
        """
        Show the about dialog.
        """
        dialog = Gtk.AboutDialog()
        dialog.set_transient_for(self.window)
        dialog.set_modal(True)
        dialog.set_authors(("Micah Carrick <micah@quixotix.com>",))
        dialog.set_copyright("Copyright (c) 2011, Quixotix Software LLC")
        dialog.set_logo(self._get_app_icon_pixbuf(128))
        dialog.set_program_name(APP_NAME)
        dialog.set_version(APP_VERSION)
        dialog.set_comments(APP_DESCRIPTION)
        dialog.run()
        dialog.destroy()

    def on_icon_entry_changed(self, entry, data=None):
        """
        Update the primary icon as the user enters text.
        """
        icon = entry.get_text()
        self._ui_value_changed("Icon", icon)

        icon_theme = Gtk.IconTheme.get_default()
        if os.path.exists(icon):
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon, 16, 16)
            entry.set_property("primary-icon-pixbuf", pixbuf)
        elif icon_theme.has_icon(icon):
            #pixbuf = icon_theme.load_icon(icon, 16, Gtk.IconLookupFlags.USE_BUILTIN)
            entry.set_property("primary-icon-name", icon)
        else:
            entry.set_property("primary-icon-name", Gtk.STOCK_MISSING_IMAGE)

    def on_icon_entry_icon_press(self, entry, icon_pos, event, data=None):
        """
        Show the icon preview dialog if the user clicks the icon entry's primary
        icon.
        """
        if not self._entry:
            return
        builder = Gtk.Builder()
        try:
            builder.add_from_file(os.path.join(DATA_DIR, "icon_preview_dialog.ui"))
        except Exception as e:
            sys.exit("Failed to load UI file: %s." % str(e))
        dialog = builder.get_object("icon_preview_dialog")
        label = builder.get_object("icon_name_label")
        label.set_markup("<b>%s</b>" % self._entry.getIcon())
        button = builder.get_object("close_button")
        button.connect("clicked", lambda button,dialog: dialog.destroy(), dialog)
        dialog.set_transient_for(self.window)
        
        for size in (16,24,32,48,64,128):
            image = builder.get_object("image_%s" % str(size))
            if image:
                image.set_from_pixbuf(self._entry.getIconPixbuf(size))
        dialog.show()
    
    def on_save_button_clicked(self, button, data=None):
        self.save_file(self._entry.filename)
    
    def on_terminal_button_toggled(self, button, data=None):
        self._ui_value_changed("Terminal", button.get_active())
        
    def on_treeview_button_press_event(self, treeview, event, data=None):
        # if user needs to save...
            # return True
        return False
  
    def on_main_window_map_event(self, window, event, data=None):
        #while Gtk.events_pending():
        #    Gtk.main_iteration()
        pass
    
    def on_main_window_show(self, window, data=None):
        
        while Gtk.events_pending():
            Gtk.main_iteration()
        self._load_treeview()
        pass
    
    def on_name_entry_changed(self, entry, data=None):
        self._ui_value_changed("Name", entry.get_text())
            
    def on_notebook_switch_page(self, notebook, page, data=None):
        index = self._notebook.get_current_page()
        if index == self.SOURCE_TAB:
            self._update_source_tab()
        elif index == self.ADVANCED_TAB:
            self._update_advanced_tab()
        
        
    def on_treeview_selection_changed(self, selection, data=None):
        """
        Change the currently selected desktop entry.
        """
        model, iter = selection.get_selected()
        if model and iter:
            self.close_file()
            self.open_file(model.get_value(iter, 2))
     
    def open_file(self, desktop_file):
        """
        Open the specified desktop file.
        """
        # TODO make sure this desktop file is selected in the list
        try:
            self._entry = Entry(desktop_file)
        except ParsingError, e:
            self.error_dialog(e)
            return
        
        self._load_desktop_entry_ui()
        # validate in save
        """
        try:
            entry.validate()
        except ValidationError, e:
            self.error_dialog(e)
            return
        """
          
    def quit(self, widget=None, data=None):
        """
        Used as callback for both user quit (File > Quit) and window manager
        killing the window.
        """
        Gtk.main_quit()
        
    def run(self):
        """
        Show the main application window and enter GTK+ main loop.
        """
        self.window.show()
        Gtk.main()
    
    def save_dialog(self):
        """
        Return a user-selected save filename or None if the user cancels.
        """
        filename = None
        
        chooser = Gtk.FileChooserDialog("Save File...", self.window,
                                        Gtk.FileChooserAction.SAVE,
                                        (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, 
                                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK))
        if self._entry and self._entry.filename:
            chooser.set_filename(self._entry.filename)
        else:
            for path in xdg_data_dirs:
                path = os.path.join(path, "applications")
                if os.path.exists(path) and os.access(path, os.W_OK):
                    chooser.set_current_folder(path)
                    break
                    
        response = chooser.run()
        if response == Gtk.ResponseType.OK: 
            filename = chooser.get_filename()
        chooser.destroy()
        if filename:
            if not self.overwrite_existing_file_dialog(filename):
                filename = None
        return filename
        
    def save_file(self, filename):
        self._entry.write(filename)
        self._load_treeview()
        self.set_modified(False)
        self._load_desktop_entry_ui()
        
    def set_modified(self, modified=True):
        """
        Set the modified flag on the entry and update the titlebar
        """
        self._entry.is_modified = modified
        self._update_ui()
    
    def _ui_value_changed(self, key, value):
        """
        Generic method to handle user changes to the Entry via the GUI.
        """
        if self._state == self.STATE_NORMAL:
            self.set_modified(True)
        else:
            return # do not continue if we're loading UI
            
        self._entry.set(key, value)
    
    def _update_advanced_tab(self):
        """
        Update the advanced tab based on the current state of the Entry.        
        """
        model = self._advanced_treeview.get_model()
        model.clear()
        for key, tooltip, t in self.ALL_KEYS:
            try:
                value = self._entry.get(key)
            except:
                value = None
            model.append((key, value, tooltip,))
        
    def _update_source_tab(self):
        """
        Update the source tab with the contents of what the .desktop file would
        look like based on the current, possibly unsaved entry.
        """
        # temporarily change entry filename to a temp file to write it's output
        entry = self._entry
        original_filename = self._entry.filename
        (fd, filename) = tempfile.mkstemp(suffix=".desktop")
        entry.write(filename)

        # load temp file into sourceview
        self._sourceview.set_editable(False)
        buffer = self._sourceview.get_buffer()
        with open(entry.filename, 'r') as f:
            buffer.set_text(f.read())
        f.closed
        self._sourceview.set_editable(True)
        
        # clean up
        if fd:
            os.close(fd)
        if filename:
            os.remove(filename)
        entry.filename = original_filename
        
    def _update_ui(self):
        """
        Update the UI to reflect the state of the the current Entry.
        """
        entry = self._entry
        
        # titlebar
        if not entry:
            self.window.set_title(APP_NAME)
        else:
            read_only = modified_indicator = ""
            if entry.isReadOnly():
                read_only = "(read-only)"
            if entry.is_modified:
                modified_indicator = "*"
            self.window.set_title("%s%s %s - %s" % (modified_indicator,
                                                    os.path.basename(entry.filename), 
                                                    read_only,
                                                    APP_NAME))
        # save buttons 
        if entry and entry.isModified() and not entry.isReadOnly():
            [widget.set_sensitive(True) for widget in self._save_widgets]
        else:
            [widget.set_sensitive(False) for widget in self._save_widgets]
         
