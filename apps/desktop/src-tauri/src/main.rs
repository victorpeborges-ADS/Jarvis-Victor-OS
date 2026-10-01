// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if desktop_lib::runtime_manager::run_test_helper_from_args() {
        return;
    }
    desktop_lib::run()
}
