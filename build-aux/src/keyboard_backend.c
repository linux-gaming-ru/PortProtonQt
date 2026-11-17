#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/XKBlib.h>
#include <string.h>
#include <wayland-client.h>

struct wl_display *portproton_keyboard_wayland_connect(const char *name)
{
    return wl_display_connect(name);
}

Display *portproton_keyboard_x11_open_display(const char *name)
{
    Display *display = XOpenDisplay(name);
    if (display)
        XkbSelectEvents(display, XkbUseCoreKbd,
                        XkbMapNotifyMask | XkbNewKeyboardNotifyMask,
                        XkbMapNotifyMask | XkbNewKeyboardNotifyMask);
    return display;
}

static int keyboard_group_name(Display *display, unsigned int group,
                               char *buffer, size_t size)
{
    XkbDescPtr keyboard = XkbGetMap(display, 0, XkbUseCoreKbd);
    int found = 0;
    if (!keyboard)
        return 0;
    if (XkbGetNames(display, XkbGroupNamesMask, keyboard) == Success &&
        keyboard->names && group < XkbNumKbdGroups && keyboard->names->groups[group]) {
        char *name = XGetAtomName(display, keyboard->names->groups[group]);
        if (name) {
            size_t length = strlen(name);
            found = length > 0 && length < size;
            if (found)
                memcpy(buffer, name, length + 1);
            XFree(name);
        }
    }
    XkbFreeKeyboard(keyboard, XkbAllComponentsMask, True);
    return found;
}

int portproton_keyboard_x11_layout_name(Display *display, unsigned int group,
                                      char *buffer, size_t size)
{
    const long property_length = 1024;
    Atom property = XInternAtom(display, "_XKB_RULES_NAMES", True);
    Atom type;
    int format;
    unsigned long length, remaining;
    unsigned char *data = NULL;
    if (!buffer || size == 0)
        return 0;
    if (!property)
        return keyboard_group_name(display, group, buffer, size);
    if (XGetWindowProperty(display, DefaultRootWindow(display), property, 0,
                          property_length, False, XA_STRING, &type, &format,
                          &length, &remaining, &data) != Success || !data)
        return keyboard_group_name(display, group, buffer, size);
    char *start = (char *)data;
    char *end = start + length;
    for (unsigned int field = 0; field < 2 && start < end; ++field) {
        char *separator = memchr(start, '\0', (size_t)(end - start));
        start = separator ? separator + 1 : end;
    }
    char *layouts_end = memchr(start, '\0', (size_t)(end - start));
    if (!layouts_end)
        layouts_end = end;
    for (unsigned int index = 0; index < group && start < layouts_end; ++index) {
        char *separator = memchr(start, ',', (size_t)(layouts_end - start));
        start = separator ? separator + 1 : layouts_end;
    }
    char *separator = memchr(start, ',', (size_t)(layouts_end - start));
    size_t count = (size_t)((separator ? separator : layouts_end) - start);
    int found = format == 8 && count > 0 && count < size;
    if (found) {
        memcpy(buffer, start, count);
        buffer[count] = '\0';
    }
    XFree(data);
    return found || keyboard_group_name(display, group, buffer, size);
}
int portproton_keyboard_x11_state(Display *display, unsigned int *values)
{
    XkbStateRec state;
    int opcode, event_base, error_base;
    int major = XkbMajorVersion, minor = XkbMinorVersion;
    if (!XkbQueryExtension(display, &opcode, &event_base, &error_base, &major, &minor))
        return 0;
    /* Reading XKB events also invalidates Xlib's cached keyboard map. */
    while (XPending(display)) {
        XkbEvent event;
        XNextEvent(display, &event.core);
        if (event.type == MappingNotify)
            XRefreshKeyboardMapping(&event.core.xmapping);
        else if (event.type == event_base && event.any.xkb_type == XkbMapNotify)
            XkbRefreshKeyboardMapping(&event.map);
    }
    if (XkbGetState(display, XkbUseCoreKbd, &state) != Success)
        return 0;
    values[0] = state.group;
    values[1] = state.mods;
    values[2] = state.locked_mods;
    return 1;
}

unsigned int portproton_keyboard_x11_keysym(Display *display, unsigned int code,
                                              unsigned int mask)
{
    unsigned int consumed;
    KeySym symbol;
    if (!XkbLookupKeySym(display, code, mask, &consumed, &symbol))
        return 0;
    return (unsigned int)symbol;
}

static const struct wl_message keyboard_group_requests[] = {
    {"set_group", "u", NULL}, {"destroy", "", NULL}
};
static const struct wl_message keyboard_group_events[] = {{"group", "u", NULL}};
static const struct wl_interface keyboard_group_interface = {
    "zcosmic_keyboard_layout_v1", 1, 2, keyboard_group_requests, 1, keyboard_group_events
};
static const struct wl_interface *keyboard_manager_types[] = {
    &keyboard_group_interface, &wl_keyboard_interface
};
static const struct wl_message keyboard_manager_requests[] = {
    {"get_keyboard_layout", "no", keyboard_manager_types}, {"destroy", "", NULL}
};
static const struct wl_interface keyboard_manager_interface = {
    "zcosmic_keyboard_layout_manager_v1", 1, 2, keyboard_manager_requests, 0, NULL
};

static const struct wl_message keyboard_layer_requests[] = {
    {"set_size", "uu", NULL}, {"set_anchor", "u", NULL},
    {"set_exclusive_zone", "i", NULL}, {"set_margin", "iiii", NULL},
    {"set_keyboard_interactivity", "u", NULL}, {"get_popup", "o", NULL},
    {"ack_configure", "u", NULL}, {"destroy", "", NULL}
};
static const struct wl_message keyboard_layer_events[] = {
    {"configure", "uuu", NULL}, {"closed", "", NULL}
};
static const struct wl_interface keyboard_layer_interface = {
    "zwlr_layer_surface_v1", 1, 8, keyboard_layer_requests, 2, keyboard_layer_events
};
static const struct wl_interface *keyboard_shell_types[] = {
    &keyboard_layer_interface, &wl_surface_interface, &wl_output_interface, NULL, NULL
};
static const struct wl_message keyboard_shell_requests[] = {
    {"get_layer_surface", "no?ous", keyboard_shell_types}
};
static const struct wl_interface keyboard_shell_interface = {
    "zwlr_layer_shell_v1", 1, 1, keyboard_shell_requests, 0, NULL
};

const struct wl_interface *portproton_keyboard_wayland_interface(const char *name)
{
    const struct wl_interface *interfaces[] = {
        &wl_registry_interface, &wl_seat_interface, &wl_keyboard_interface,
        &keyboard_group_interface, &keyboard_manager_interface,
        &wl_callback_interface, &wl_compositor_interface, &wl_shm_interface,
        &wl_surface_interface, &wl_output_interface, &wl_region_interface,
        &wl_shm_pool_interface, &wl_buffer_interface, &wl_pointer_interface,
        &wl_touch_interface, &keyboard_layer_interface, &keyboard_shell_interface
    };
    for (size_t index = 0; index < sizeof(interfaces) / sizeof(interfaces[0]); ++index) {
        if (strcmp(name, interfaces[index]->name) == 0)
            return interfaces[index];
    }
    return NULL;
}

enum keyboard_probe_global {
    KEYBOARD_PROBE_COMPOSITOR,
    KEYBOARD_PROBE_SHM,
    KEYBOARD_PROBE_LAYER_SHELL,
    KEYBOARD_PROBE_GLOBAL_COUNT
};

static void keyboard_probe_global(void *data, struct wl_registry *registry,
                                  uint32_t name, const char *interface, uint32_t version)
{
    uint32_t *globals = data;
    const char *required[] = {"wl_compositor", "wl_shm", "zwlr_layer_shell_v1"};
    (void)registry;
    (void)version;
    for (size_t index = 0; index < sizeof(required) / sizeof(required[0]); ++index) {
        if (strcmp(interface, required[index]) == 0)
            globals[index] = name;
    }
}

static void keyboard_probe_removed(void *data, struct wl_registry *registry, uint32_t name)
{
    uint32_t *globals = data;
    (void)registry;
    for (size_t index = 0; index < KEYBOARD_PROBE_GLOBAL_COUNT; ++index) {
        if (globals[index] == name)
            globals[index] = 0;
    }
}

int portproton_keyboard_has_layer_shell(void)
{
    struct wl_display *display = wl_display_connect(NULL);
    if (!display)
        return 0;
    uint32_t globals[KEYBOARD_PROBE_GLOBAL_COUNT] = {0};
    const struct wl_registry_listener listener = {
        .global = keyboard_probe_global, .global_remove = keyboard_probe_removed
    };
    struct wl_registry *registry = wl_display_get_registry(display);
    if (!registry) {
        wl_display_disconnect(display);
        return 0;
    }
    int ready = wl_registry_add_listener(registry, &listener, globals) == 0 &&
                wl_display_roundtrip(display) >= 0;
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return ready && globals[KEYBOARD_PROBE_COMPOSITOR] &&
           globals[KEYBOARD_PROBE_SHM] && globals[KEYBOARD_PROBE_LAYER_SHELL];
}
