#include <SDL3/SDL.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define AXIS_ACTIVATION_THRESHOLD 16000

typedef struct {
    SDL_Gamepad *gamepad;
    SDL_JoystickID instance_id;
    int sdl_type;
    bool buttons[SDL_GAMEPAD_BUTTON_COUNT];
    bool axes_active[SDL_GAMEPAD_AXIS_COUNT];
} GamepadEntry;

typedef struct {
    GamepadEntry *entries;
    int count;
    SDL_JoystickID active_instance_id;
} PortProtonGamepad;

static bool has_gamepad(const PortProtonGamepad *gamepads,
                        SDL_JoystickID instance_id)
{
    for (int index = 0; index < gamepads->count; index++) {
        if (gamepads->entries[index].instance_id == instance_id) {
            return true;
        }
    }
    return false;
}

static bool add_gamepad(PortProtonGamepad *gamepads,
                        SDL_JoystickID instance_id)
{
    SDL_Gamepad *gamepad = SDL_OpenGamepad(instance_id);
    if (gamepad == NULL) {
        return false;
    }
    GamepadEntry *entries = realloc(
        gamepads->entries, sizeof(*entries) * (gamepads->count + 1));
    if (entries == NULL) {
        SDL_CloseGamepad(gamepad);
        return SDL_SetError("Failed to allocate gamepad handle");
    }
    gamepads->entries = entries;
    GamepadEntry entry = {0};
    entry.gamepad = gamepad;
    entry.instance_id = instance_id;
    entry.sdl_type = SDL_GetGamepadTypeForID(instance_id);
    entries[gamepads->count] = entry;
    gamepads->count++;
    return true;
}

static void remove_disconnected(PortProtonGamepad *gamepads)
{
    int active_count = 0;
    for (int index = 0; index < gamepads->count; index++) {
        GamepadEntry entry = gamepads->entries[index];
        if (SDL_GamepadConnected(entry.gamepad)) {
            gamepads->entries[active_count++] = entry;
        } else {
            if (gamepads->active_instance_id == entry.instance_id) {
                gamepads->active_instance_id = 0;
            }
            SDL_CloseGamepad(entry.gamepad);
        }
    }
    gamepads->count = active_count;
}

static void update_gamepads(PortProtonGamepad *gamepads)
{
    SDL_UpdateGamepads();
    remove_disconnected(gamepads);
    int count = 0;
    SDL_JoystickID *instance_ids = SDL_GetGamepads(&count);
    if (instance_ids == NULL) {
        return;
    }
    for (int index = 0; index < count; index++) {
        if (!has_gamepad(gamepads, instance_ids[index])) {
            add_gamepad(gamepads, instance_ids[index]);
        }
    }
    SDL_free(instance_ids);
}

static bool update_entry_activity(GamepadEntry *entry)
{
    bool activated = false;
    for (int button = 0; button < SDL_GAMEPAD_BUTTON_COUNT; button++) {
        bool pressed = SDL_GetGamepadButton(entry->gamepad, button);
        activated |= pressed && !entry->buttons[button];
        entry->buttons[button] = pressed;
    }
    for (int axis = 0; axis < SDL_GAMEPAD_AXIS_COUNT; axis++) {
        int value = SDL_GetGamepadAxis(entry->gamepad, axis);
        bool active = abs(value) >= AXIS_ACTIVATION_THRESHOLD;
        activated |= active && !entry->axes_active[axis];
        entry->axes_active[axis] = active;
    }
    return activated;
}

static const GamepadEntry *get_active_gamepad(const PortProtonGamepad *gamepads)
{
    if (gamepads == NULL) {
        return NULL;
    }
    for (int index = 0; index < gamepads->count; index++) {
        if (gamepads->entries[index].instance_id == gamepads->active_instance_id) {
            return &gamepads->entries[index];
        }
    }
    return NULL;
}

PortProtonGamepad *portproton_gamepad_find(void)
{
    SDL_ClearError();
    if (!SDL_InitSubSystem(SDL_INIT_GAMEPAD)) {
        return NULL;
    }
    PortProtonGamepad *result = calloc(1, sizeof(*result));
    if (result == NULL) {
        SDL_SetError("Failed to allocate gamepad collection");
        return NULL;
    }
    update_gamepads(result);
    if (result->count == 0) {
        free(result);
        SDL_ClearError();
        return NULL;
    }
    return result;
}

const char *portproton_gamepad_get_error(void)
{
    const char *error = SDL_GetError();
    return error != NULL ? error : "";
}

void portproton_gamepad_close(PortProtonGamepad *gamepad)
{
    if (gamepad == NULL) {
        return;
    }
    for (int index = 0; index < gamepad->count; index++) {
        SDL_CloseGamepad(gamepad->entries[index].gamepad);
    }
    free(gamepad->entries);
    free(gamepad);
}

bool portproton_gamepad_connected(const PortProtonGamepad *gamepad)
{
    return gamepad != NULL && gamepad->count > 0;
}

void portproton_gamepad_update(PortProtonGamepad *gamepad)
{
    if (gamepad != NULL) {
        update_gamepads(gamepad);
        for (int index = 0; index < gamepad->count; index++) {
            if (update_entry_activity(&gamepad->entries[index])) {
                gamepad->active_instance_id = gamepad->entries[index].instance_id;
            }
        }
    }
}

int portproton_gamepad_get_button(const PortProtonGamepad *gamepad, int button)
{
    const GamepadEntry *active = get_active_gamepad(gamepad);
    if (active == NULL) {
        return 0;
    }
    return SDL_GetGamepadButton(active->gamepad, button);
}

int16_t portproton_gamepad_get_axis(const PortProtonGamepad *gamepad, int axis)
{
    const GamepadEntry *active = get_active_gamepad(gamepad);
    if (active == NULL) {
        return 0;
    }
    return SDL_GetGamepadAxis(active->gamepad, axis);
}

uint32_t portproton_gamepad_get_active_instance_id(
    const PortProtonGamepad *gamepad)
{
    return gamepad != NULL ? gamepad->active_instance_id : 0;
}

const char *portproton_gamepad_get_name(const PortProtonGamepad *gamepad)
{
    if (gamepad == NULL || gamepad->count == 0) {
        return "";
    }
    const char *name = SDL_GetGamepadName(gamepad->entries[0].gamepad);
    return name != NULL ? name : "";
}

uint32_t portproton_gamepad_get_instance_id(const PortProtonGamepad *gamepad)
{
    return gamepad != NULL && gamepad->count > 0
        ? gamepad->entries[0].instance_id : 0;
}

int portproton_gamepad_get_type(const PortProtonGamepad *gamepad)
{
    return gamepad != NULL && gamepad->count > 0
        ? gamepad->entries[0].sdl_type : 0;
}

void portproton_gamepad_shutdown(void)
{
    SDL_QuitSubSystem(SDL_INIT_GAMEPAD);
}
