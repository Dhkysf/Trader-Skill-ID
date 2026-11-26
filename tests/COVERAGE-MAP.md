# US-to-IDX Test Coverage Map

- Total US tests: 287
- Generic: 255
- US-only: 32
- Missing (generic): 0

| US Test | Category | IDX Coverage | Notes |
| --- | --- | --- | --- |
| test_scanner.py::Universe.test_the_kept_list | US-only | - | Nasdaq Trader symbol directory |
| test_scanner.py::Universe.test_one_case_per_rule | US-only | - | Nasdaq Trader security classification rules |
| test_scanner.py::Universe.test_nextshares_rule | US-only | - | Nasdaq NextShares flag |
| test_scanner.py::Universe.test_not_a_symbol_file | US-only | - | Nasdaq Trader pipe-delimited file parser |
| test_scanner.py::Time.test_dst_and_clock | US-only | - | US Eastern DST |
| test_scanner.py::Spark.test_a_real_spark_answer | generic | test_idx_parity.py::IdxScannerParityTest.test_parse_spark_and_in_progress_daily_close | covered |
| test_scanner.py::Spark.test_spark_errors | generic | test_idx_parity.py::IdxScannerParityTest.test_spark_errors_and_urls | covered |
| test_scanner.py::Spark.test_urls | generic | test_idx_parity.py::IdxScannerParityTest.test_spark_errors_and_urls | covered |
| test_scanner.py::Network.test_429_falls_back_then_waits_once | generic | test_idx_parity.py::IdxScannerParityTest.test_network_429_5xx_404_and_partial | covered |
| test_scanner.py::Network.test_5xx_goes_to_query1_without_waiting | generic | test_idx_parity.py::IdxScannerParityTest.test_network_429_5xx_404_and_partial | covered |
| test_scanner.py::Network.test_429_for_good_is_reported_as_partial | generic | test_idx_parity.py::IdxScannerParityTest.test_network_429_5xx_404_and_partial | covered |
| test_scanner.py::Network.test_a_404_is_final | generic | test_idx_parity.py::IdxScannerParityTest.test_network_429_5xx_404_and_partial | covered |
| test_scanner.py::Daily.test_setups_before_the_open | generic | test_idx_parity.py::IdxScannerParityTest.test_daily_setups_and_rsi_math | covered |
| test_scanner.py::Daily.test_the_in_progress_bar_is_dropped | generic | test_idx_parity.py::IdxScannerParityTest.test_parse_spark_and_in_progress_daily_close | covered |
| test_scanner.py::Daily.test_half_day_bar_completes_at_one | generic | test_idx_parity.py::IdxScannerParityTest.test_parse_spark_and_in_progress_daily_close | covered |
| test_scanner.py::Daily.test_liquidity_filter | generic | test_idx_parity.py::IdxScannerParityTest.test_daily_liquidity_and_short_empty_charts | covered |
| test_scanner.py::Daily.test_short_and_empty_charts | generic | test_idx_parity.py::IdxScannerParityTest.test_daily_liquidity_and_short_empty_charts | covered |
| test_scanner.py::Daily.test_rsi_matches_the_reel_math | generic | test_idx_parity.py::IdxScannerParityTest.test_daily_setups_and_rsi_math | covered |
| test_scanner.py::Orb.test_the_reel_scan_at_1015 | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_scan_sorting_price_floor_and_cutoff | covered |
| test_scanner.py::Orb.test_price_floor | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_scan_sorting_price_floor_and_cutoff | covered |
| test_scanner.py::Orb.test_in_progress_bar_and_no_breakout_yet | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_scan_sorting_price_floor_and_cutoff | covered |
| test_scanner.py::Orb.test_the_live_tick_is_dropped | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_live_tick_missing_bar_and_30m_range | covered |
| test_scanner.py::Orb.test_stage_one_is_a_necessary_condition | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_two_stage_confirm_and_cap | covered |
| test_scanner.py::Orb.test_confirm_uses_the_v8_highs | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_two_stage_confirm_and_cap | covered |
| test_scanner.py::Orb.test_a_missing_bar_makes_a_chart_unusable | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_live_tick_missing_bar_and_30m_range | covered |
| test_scanner.py::Orb.test_winter_time_half_day_and_a_30_minute_range | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_live_tick_missing_bar_and_30m_range | covered |
| test_scanner.py::Orb.test_window_messages | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_window_messages_and_cli_errors | covered |
| test_scanner.py::LiveFiveMinute.test_in_progress_bar_and_live_tick_are_dropped | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_live_tick_missing_bar_and_30m_range | covered |
| test_scanner.py::LiveFiveMinute.test_tsla_broke_its_range_at_ten | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_scan_sorting_price_floor_and_cutoff | covered |
| test_scanner.py::LiveFiveMinute.test_stage_two_cap_takes_the_most_traded | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_two_stage_confirm_and_cap | covered |
| test_scanner.py::Cli.test_universe_daily_orb_end_to_end | generic | test_idx_parity.py::IdxScannerParityTest.test_cli_end_to_end_folder_lists_and_json | covered |
| test_scanner.py::Cli.test_partial_stage_two_is_said | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_two_stage_confirm_and_cap | covered |
| test_scanner.py::Cli.test_plain_messages_and_exit_codes | generic | test_idx_parity.py::IdxScannerParityTest.test_orb_window_messages_and_cli_errors | covered |
| test_scanner.py::Cli.test_offline_folder_of_v8_files | generic | test_idx_parity.py::IdxScannerParityTest.test_cli_end_to_end_folder_lists_and_json | covered |
| test_scanner.py::Cli.test_symbol_lists | generic | test_idx_parity.py::IdxScannerParityTest.test_cli_end_to_end_folder_lists_and_json | covered |
| test_scanner.py::Cli.test_daily_json | generic | test_idx_parity.py::IdxScannerParityTest.test_cli_end_to_end_folder_lists_and_json | covered |
| test_entry.py::TheReel.test_triggers_at_1015_on_the_1010_bar | generic | test_idx_parity.py::IdxEntryParityTest.test_orb_trigger_forming_and_phases | covered |
| test_entry.py::TheReel.test_at_1012_the_1010_bar_is_still_forming | generic | test_idx_parity.py::IdxEntryParityTest.test_orb_trigger_forming_and_phases | covered |
| test_entry.py::TheReel.test_before_the_open_and_while_the_range_forms | generic | test_idx_parity.py::IdxEntryParityTest.test_orb_trigger_forming_and_phases | covered |
| test_entry.py::TheReel.test_the_live_tick_and_the_in_progress_bar_are_dropped | generic | test_idx_parity.py::IdxEntryParityTest.test_live_tick_lag_note_and_after_close | covered |
| test_entry.py::TheReel.test_after_the_close_it_stays_triggered_and_says_it_is_late | generic | test_idx_parity.py::IdxEntryParityTest.test_live_tick_lag_note_and_after_close | covered |
| test_entry.py::Rules.test_volume_confirmation_moves_the_trigger | generic | test_idx_parity.py::IdxEntryParityTest.test_volume_level_30m_and_cutoffs | covered |
| test_entry.py::Rules.test_level_setup | generic | test_idx_parity.py::IdxEntryParityTest.test_volume_level_30m_and_cutoffs | covered |
| test_entry.py::Rules.test_no_breakout_waits_then_expires_at_the_cutoff | generic | test_idx_parity.py::IdxEntryParityTest.test_expiry_and_lag_at_cutoff | covered |
| test_entry.py::Rules.test_the_bar_closing_at_the_cutoff_still_counts_when_yahoo_lags | generic | test_idx_parity.py::IdxEntryParityTest.test_expiry_and_lag_at_cutoff | covered |
| test_entry.py::Rules.test_config_cutoff | generic | test_idx_parity.py::IdxEntryParityTest.test_volume_level_30m_and_cutoffs | covered |
| test_entry.py::Rules.test_bad_inputs | generic | test_idx_parity.py::IdxEntryParityTest.test_bad_inputs_and_calendar_empty_errors | covered |
| test_entry.py::Rules.test_or_minutes_30 | generic | test_idx_parity.py::IdxEntryParityTest.test_volume_level_30m_and_cutoffs | covered |
| test_entry.py::OneMinute.test_wick_and_close_at_the_high_do_not_trigger | generic | test_idx_parity.py::IdxEntryParityTest.test_one_minute_rules_null_bar_and_mismatch | covered |
| test_entry.py::OneMinute.test_null_bar_tick_and_volume | generic | test_idx_parity.py::IdxEntryParityTest.test_one_minute_rules_null_bar_and_mismatch | covered |
| test_entry.py::OneMinute.test_the_file_and_the_interval_must_agree | generic | test_idx_parity.py::IdxEntryParityTest.test_one_minute_rules_null_bar_and_mismatch | covered |
| test_entry.py::Calendar.test_dst_both_sides | US-only | - | US Eastern DST |
| test_entry.py::Calendar.test_half_day_moves_the_cutoff_up | US-only | - | NYSE half-day early close |
| test_entry.py::Calendar.test_weekend_holiday_and_empty_data | generic | test_idx_parity.py::IdxEntryParityTest.test_bad_inputs_and_calendar_empty_errors | covered |
| test_entry.py::Calendar.test_yahoo_errors | generic | test_idx_parity.py::IdxEntryParityTest.test_bad_inputs_and_calendar_empty_errors | covered |
| test_entry.py::Network.test_url_and_429_retry_once_after_a_pause | generic | test_idx_parity.py::IdxEntryParityTest.test_network_retry_fallback_404_and_ranges | covered |
| test_entry.py::Network.test_429_twice_falls_back_to_query1 | generic | test_idx_parity.py::IdxEntryParityTest.test_network_retry_fallback_404_and_ranges | covered |
| test_entry.py::Network.test_5xx_falls_back_without_waiting | generic | test_idx_parity.py::IdxEntryParityTest.test_network_retry_fallback_404_and_ranges | covered |
| test_entry.py::Network.test_still_busy_is_one_plain_error | generic | test_idx_parity.py::IdxEntryParityTest.test_network_retry_fallback_404_and_ranges | covered |
| test_entry.py::Network.test_unknown_ticker_404 | generic | test_idx_parity.py::IdxEntryParityTest.test_network_retry_fallback_404_and_ranges | covered |
| test_entry.py::Network.test_ranges_for_past_sessions | generic | test_idx_parity.py::IdxEntryParityTest.test_network_retry_fallback_404_and_ranges | covered |
| test_entry.py::Watch.test_fires_on_the_first_closed_bar_not_the_spike_in_progress | generic | test_idx_parity.py::IdxEntryParityTest.test_watch_trigger_lag_preopen_and_doze | covered |
| test_entry.py::Watch.test_waits_for_yahoo_to_catch_up | generic | test_idx_parity.py::IdxEntryParityTest.test_watch_trigger_lag_preopen_and_doze | covered |
| test_entry.py::Watch.test_from_before_the_open_prints_the_range_bar_by_bar | generic | test_idx_parity.py::IdxEntryParityTest.test_watch_trigger_lag_preopen_and_doze | covered |
| test_entry.py::Watch.test_a_computer_that_dozes_off_catches_up_when_it_wakes | generic | test_idx_parity.py::IdxEntryParityTest.test_watch_trigger_lag_preopen_and_doze | covered |
| test_entry.py::Watch.test_expires_and_until | generic | test_idx_parity.py::IdxEntryParityTest.test_watch_expiry_until_closed_and_errors | covered |
| test_entry.py::Watch.test_closed_day_and_repeated_errors | generic | test_idx_parity.py::IdxEntryParityTest.test_watch_expiry_until_closed_and_errors | covered |
| test_entry.py::Cli.test_check_write_is_the_contract_shape | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_check_write_json_offline_and_flags | covered |
| test_entry.py::Cli.test_check_waiting_json_and_exit_codes | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_check_write_json_offline_and_flags | covered |
| test_entry.py::Cli.test_offline_gz_folder_and_mismatch | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_check_write_json_offline_and_flags | covered |
| test_entry.py::Cli.test_longs_only_and_flag_errors | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_check_write_json_offline_and_flags | covered |
| test_entry.py::Cli.test_config_is_read | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_config_watch_and_watchlist | covered |
| test_entry.py::Cli.test_watch_replays_the_file_and_writes_the_entry | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_config_watch_and_watchlist | covered |
| test_entry.py::Cli.test_watchlist | generic | test_idx_parity.py::IdxEntryParityTest.test_cli_config_watch_and_watchlist | covered |
| test_entry.py::SkillDoc.test_skill_md | US-only | - | US TSLA reel numbers in SKILL.md |
| test_exit.py::Math.test_the_reel_or_mid_1r | generic | test_idx_parity.py::IdxExitParityTest.test_or_mid_or_low_pct_atr_and_targets | covered |
| test_exit.py::Math.test_the_default_2r | generic | test_idx_parity.py::IdxExitParityTest.test_or_mid_or_low_pct_atr_and_targets | covered |
| test_exit.py::Math.test_raw_yahoo_floats_give_the_same_cents | generic | test_idx_parity.py::IdxExitParityTest.test_or_mid_or_low_pct_atr_and_targets | covered |
| test_exit.py::Math.test_other_stops | generic | test_idx_parity.py::IdxExitParityTest.test_or_mid_or_low_pct_atr_and_targets | covered |
| test_exit.py::Math.test_target_rounds_half_up_and_price_targets | generic | test_idx_parity.py::IdxExitParityTest.test_or_mid_or_low_pct_atr_and_targets | covered |
| test_exit.py::Math.test_refusals_say_why | generic | test_idx_parity.py::IdxExitParityTest.test_math_refusals_and_atr_session_bars | covered |
| test_exit.py::Math.test_atr_on_the_session_bars | generic | test_idx_parity.py::IdxExitParityTest.test_math_refusals_and_atr_session_bars | covered |
| test_exit.py::Cli.test_entry_to_plan_end_to_end | generic | test_idx_parity.py::IdxExitParityTest.test_cli_end_to_end_show_and_manual_flags | covered |
| test_exit.py::Cli.test_manual_flags_and_json | generic | test_idx_parity.py::IdxExitParityTest.test_cli_end_to_end_show_and_manual_flags | covered |
| test_exit.py::Cli.test_atr_stop_reads_bars | generic | test_idx_parity.py::IdxExitParityTest.test_cli_atr_refusals_and_flat_by | covered |
| test_exit.py::Cli.test_refusals_from_the_cli | generic | test_idx_parity.py::IdxExitParityTest.test_cli_atr_refusals_and_flat_by | covered |
| test_exit.py::Cli.test_flat_by_config_half_day_and_late_entries | US-only | - | NYSE half-day early close |
| test_exit.py::Cli.test_show_without_a_plan | generic | test_idx_parity.py::IdxExitParityTest.test_cli_end_to_end_show_and_manual_flags | covered |
| test_exit.py::SkillDoc.test_skill_md | US-only | - | US TSLA reel numbers in SKILL.md |
| test_timemachine.py::Reel.test_the_reel_odds | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_mc_fields_bands_history_and_report | covered |
| test_timemachine.py::Reel.test_bit_for_bit_with_the_reel_sim | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_mc_fields_bands_history_and_report | covered |
| test_timemachine.py::Reel.test_the_history_replay | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_mc_fields_bands_history_and_report | covered |
| test_timemachine.py::Reel.test_the_verdict_says_coin_flip | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_verdict_thresholds_1r_and_2r | covered |
| test_timemachine.py::Reel.test_bands_start_at_the_entry | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_mc_fields_bands_history_and_report | covered |
| test_timemachine.py::Reel.test_the_plan_is_carried_through | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_mc_fields_bands_history_and_report | covered |
| test_timemachine.py::Reel.test_the_text_report | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_mc_fields_bands_history_and_report | covered |
| test_timemachine.py::Seeds.test_same_seed_same_numbers | generic | test_idx.py::IdxTimeMachineRestTest.test_determinism_and_us_tsla_reproduction | covered |
| test_timemachine.py::Seeds.test_another_seed_gives_other_numbers | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_seeds_window_and_replays | covered |
| test_timemachine.py::Seeds.test_the_draws_are_stable_across_pythons | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_seeds_window_and_replays | covered |
| test_timemachine.py::Seeds.test_window_and_replays | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_seeds_window_and_replays | covered |
| test_timemachine.py::Bars.test_the_in_progress_tick_is_dropped | generic | test_idx.py::IdxTimeMachineTest.test_slot_counts_and_excluded_bars | covered |
| test_timemachine.py::Bars.test_now_pins_the_clock | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_bars_filtering_clock_short_and_min_sessions | covered |
| test_timemachine.py::Bars.test_daylight_saving | US-only | - | US Eastern DST |
| test_timemachine.py::Bars.test_a_half_day_is_left_out | generic | test_idx.py::IdxTimeMachineTest.test_slot_counts_and_excluded_bars | covered |
| test_timemachine.py::Bars.test_today_is_not_in_the_pool | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_bars_filtering_clock_short_and_min_sessions | covered |
| test_timemachine.py::Bars.test_a_missing_price_is_dropped | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_bars_filtering_clock_short_and_min_sessions | covered |
| test_timemachine.py::Bars.test_empty_and_broken_data | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_bars_filtering_clock_short_and_min_sessions | covered |
| test_timemachine.py::Bars.test_fewer_than_20_sessions_is_refused | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_bars_filtering_clock_short_and_min_sessions | covered |
| test_timemachine.py::Bars.test_an_early_close_day_ends_the_replay_at_1_pm | US-only | - | NYSE 1:00 PM early close |
| test_timemachine.py::Bars.test_the_data_must_be_the_plans_ticker | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_checks_and_until | covered |
| test_timemachine.py::Plans.test_an_entry_not_in_the_data_is_refused | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_checks_and_until | covered |
| test_timemachine.py::Plans.test_plan_checks | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_checks_and_until | covered |
| test_timemachine.py::Plans.test_entry_bar_or_entry_time_alone | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_checks_and_until | covered |
| test_timemachine.py::Plans.test_until_cuts_the_replay | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_checks_and_until | covered |
| test_timemachine.py::Plans.test_an_entry_outside_its_bar_is_flagged | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_warnings_rules_non_orb_and_sell | covered |
| test_timemachine.py::Plans.test_stop_rounds_away_from_the_entry | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_warnings_rules_non_orb_and_sell | covered |
| test_timemachine.py::Plans.test_the_stop_rule_is_worked_out_when_not_given | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_warnings_rules_non_orb_and_sell | covered |
| test_timemachine.py::Plans.test_a_setup_other_than_orb_skips_the_history | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_warnings_rules_non_orb_and_sell | covered |
| test_timemachine.py::Plans.test_a_sell_plan_mirrors_the_rules | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_plan_warnings_rules_non_orb_and_sell | covered |
| test_timemachine.py::Plans.test_the_verdict_thresholds_at_1r | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_verdict_thresholds_1r_and_2r | covered |
| test_timemachine.py::Plans.test_a_2r_target_is_judged_against_its_break_even | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_verdict_thresholds_1r_and_2r | covered |
| test_timemachine.py::Plans.test_2r_on_the_fixture_near_break_even | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_verdict_thresholds_1r_and_2r | covered |
| test_timemachine.py::Plans.test_2r_on_the_fixture_a_clear_lean | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_verdict_thresholds_1r_and_2r | covered |
| test_timemachine.py::Network.test_url_and_user_agent | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Network.test_429_waits_retries_then_falls_back_to_query1 | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Network.test_one_429_then_ok | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Network.test_5xx_falls_back | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Network.test_rate_limited_everywhere_is_one_plain_line | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Network.test_404 | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Network.test_run_over_the_network_path | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_network_retry_fallback_and_404 | covered |
| test_timemachine.py::Cli.test_run_with_the_plan_end_to_end | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_cli_run_json_flags_folder_errors_and_chart | covered |
| test_timemachine.py::Cli.test_json_output | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_cli_run_json_flags_folder_errors_and_chart | covered |
| test_timemachine.py::Cli.test_the_plan_as_flags_matches_the_file | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_cli_run_json_flags_folder_errors_and_chart | covered |
| test_timemachine.py::Cli.test_offline_folder_and_default_paths | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_cli_run_json_flags_folder_errors_and_chart | covered |
| test_timemachine.py::Cli.test_errors_are_one_plain_line | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_cli_run_json_flags_folder_errors_and_chart | covered |
| test_timemachine.py::Cli.test_chart | generic | test_idx_parity.py::IdxTimeMachineParityTest.test_cli_run_json_flags_folder_errors_and_chart | covered |
| test_budget.py::TheReel.test_config_example_is_the_contract | generic | test_idx_parity.py::IdxBudgetParityTest.test_config_example_and_limit_order | covered |
| test_budget.py::TheReel.test_tsla_is_8_shares_bound_by_the_max_loss | generic | test_idx.py::IdxBudgetTest.test_lot_rounding_3_7_lots_to_3_lots_and_rp_formatting | covered |
| test_budget.py::TheReel.test_the_bracket_order | generic | test_idx.py::IdxBudgetTest.test_lot_rounding_3_7_lots_to_3_lots_and_rp_formatting | covered |
| test_budget.py::TheReel.test_the_fixture_orders_file_is_what_it_writes | generic | test_idx.py::IdxBudgetTest.test_cli_writes_idx_order | covered |
| test_budget.py::TheReel.test_a_limit_order | generic | test_idx_parity.py::IdxBudgetParityTest.test_config_example_and_limit_order | covered |
| test_budget.py::TheReel.test_cli_writes_one_bracket_order | generic | test_idx.py::IdxBudgetTest.test_cli_writes_idx_order | covered |
| test_budget.py::TheReel.test_cli_json_and_limit | generic | test_idx_parity.py::IdxBudgetParityTest.test_config_example_and_limit_order | covered |
| test_budget.py::PlanRules.test_zero_shares_is_a_plain_refusal | generic | test_idx.py::IdxBudgetTest.test_under_one_lot_refused | covered |
| test_budget.py::PlanRules.test_each_limit_can_bind | generic | test_idx_parity.py::IdxBudgetParityTest.test_sizing_limits_each_cap_can_bind | covered |
| test_budget.py::PlanRules.test_a_fresh_higher_price_means_a_bigger_risk | generic | test_idx_parity.py::IdxBudgetParityTest.test_fresh_stale_prices_and_portfolio_cash | covered |
| test_budget.py::PlanRules.test_prices_file_is_used_only_when_fresh | generic | test_idx_parity.py::IdxBudgetParityTest.test_fresh_stale_prices_and_portfolio_cash | covered |
| test_budget.py::PlanRules.test_the_portfolio_cash_caps_the_size | generic | test_idx_parity.py::IdxBudgetParityTest.test_fresh_stale_prices_and_portfolio_cash | covered |
| test_budget.py::PlanRules.test_bad_plans | generic | test_idx_parity.py::IdxBudgetParityTest.test_min_order_bad_plans_and_cli_errors | covered |
| test_budget.py::PlanRules.test_under_the_minimum_order | generic | test_idx_parity.py::IdxBudgetParityTest.test_min_order_bad_plans_and_cli_errors | covered |
| test_budget.py::PlanRules.test_missing_plan_and_weights_only_flags | generic | test_idx_parity.py::IdxBudgetParityTest.test_min_order_bad_plans_and_cli_errors | covered |
| test_budget.py::WeightsMode.test_from_the_raw_weights | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_from_the_renormalised_weights_file | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_cli | covered |
| test_budget.py::WeightsMode.test_from_inline_weights | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_renormalised_weights | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_one_decimal_weights_stay_within_a_dollar | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_orders_are_place_stock_order_shaped | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_cli | covered |
| test_budget.py::WeightsMode.test_cents_mode_keeps_the_total | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_cap_redistributes_until_nobody_is_over | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_everything_capped_leaves_money_idle | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_slices_under_the_minimum_are_dropped_and_shared_out | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_blocked_tickers_are_dropped_first | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_top_n | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_whole_shares_need_prices | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_whole_shares_with_prices | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_whole_lots_on_idx | covered |
| test_budget.py::WeightsMode.test_no_budget_and_duplicates_are_errors | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_caps_drops_and_errors | covered |
| test_budget.py::WeightsMode.test_cli | generic | test_idx_parity.py::IdxBudgetParityTest.test_weights_mode_cli | covered |
| test_risk.py::TheReel.test_the_tsla_bracket_passes_every_check | generic | test_idx_parity.py::IdxRiskParityTest.test_pass_fields_fingerprint_and_cli | covered |
| test_risk.py::TheReel.test_nine_shares_is_blocked_by_the_max_loss_only | generic | test_idx.py::IdxRiskTest.test_short_margin_and_fee_inclusive_loss_blocks | covered |
| test_risk.py::TheReel.test_fingerprint_is_shared_with_the_broker | generic | test_idx_parity.py::IdxRiskParityTest.test_pass_fields_fingerprint_and_cli | covered |
| test_risk.py::TheReel.test_cli | generic | test_idx_parity.py::IdxRiskParityTest.test_pass_fields_fingerprint_and_cli | covered |
| test_risk.py::DayTradeChecks.test_a_stop_is_required | generic | test_idx_parity.py::IdxRiskParityTest.test_stop_target_and_reward_risk_blocks | covered |
| test_risk.py::DayTradeChecks.test_a_plan_stop_counts_but_warns | generic | test_idx_parity.py::IdxRiskParityTest.test_stop_target_and_reward_risk_blocks | covered |
| test_risk.py::DayTradeChecks.test_stop_and_target_on_the_right_side | generic | test_idx_parity.py::IdxRiskParityTest.test_stop_target_and_reward_risk_blocks | covered |
| test_risk.py::DayTradeChecks.test_reward_risk | generic | test_idx_parity.py::IdxRiskParityTest.test_stop_target_and_reward_risk_blocks | covered |
| test_risk.py::DayTradeChecks.test_a_fresh_higher_price_is_the_entry | generic | test_idx_parity.py::IdxRiskParityTest.test_price_freshness_lower_and_limit_ref | covered |
| test_risk.py::DayTradeChecks.test_a_stale_or_future_price_is_not_used | generic | test_idx_parity.py::IdxRiskParityTest.test_price_freshness_lower_and_limit_ref | covered |
| test_risk.py::DayTradeChecks.test_a_lower_price_does_not_shrink_the_risk | generic | test_idx_parity.py::IdxRiskParityTest.test_price_freshness_lower_and_limit_ref | covered |
| test_risk.py::DayTradeChecks.test_a_limit_order_uses_its_limit_price | generic | test_idx_parity.py::IdxRiskParityTest.test_price_freshness_lower_and_limit_ref | covered |
| test_risk.py::DayTradeChecks.test_daily_loss_and_trades_per_day | generic | test_idx_parity.py::IdxRiskParityTest.test_daily_loss_trades_exits_and_batch_limits | covered |
| test_risk.py::DayTradeChecks.test_exits_and_declines_do_not_count_as_trades | generic | test_idx_parity.py::IdxRiskParityTest.test_daily_loss_trades_exits_and_batch_limits | covered |
| test_risk.py::DayTradeChecks.test_the_batch_counts_toward_the_daily_limits | generic | test_idx_parity.py::IdxRiskParityTest.test_daily_loss_trades_exits_and_batch_limits | covered |
| test_risk.py::DayTradeChecks.test_entry_window_new_york_time | generic | test_idx_parity.py::IdxRiskParityTest.test_window_weekend_holiday_and_config_errors | covered |
| test_risk.py::DayTradeChecks.test_the_window_uses_new_york_time_not_the_machine | US-only | - | US New York time |
| test_risk.py::DayTradeChecks.test_pdt_guard | US-only | - | US FINRA PDT rule |
| test_risk.py::DayTradeChecks.test_a_short_entry_when_allowed | generic | test_idx.py::IdxRiskTest.test_short_margin_and_fee_inclusive_loss_blocks | covered |
| test_risk.py::DayTradeChecks.test_bracket_format | generic | test_idx_parity.py::IdxRiskParityTest.test_format_asset_options_and_bracket_blocks | covered |
| test_risk.py::DayTradeChecks.test_extended_hours | US-only | - | US extended hours |
| test_risk.py::Exits.test_getting_out_is_never_blocked_by_the_day_limits | generic | test_idx_parity.py::IdxRiskParityTest.test_exits_partial_short_and_buy_sell_batch | covered |
| test_risk.py::Exits.test_a_partial_exit_and_the_rest | generic | test_idx_parity.py::IdxRiskParityTest.test_exits_partial_short_and_buy_sell_batch | covered |
| test_risk.py::Exits.test_format_asset_and_short_still_apply_to_a_sell | generic | test_idx_parity.py::IdxRiskParityTest.test_exits_partial_short_and_buy_sell_batch | covered |
| test_risk.py::Exits.test_buy_then_sell_in_one_batch | generic | test_idx_parity.py::IdxRiskParityTest.test_exits_partial_short_and_buy_sell_batch | covered |
| test_risk.py::V1Checks.test_the_five_buys_pass_on_a_fresh_5000_paper_account | US-only | - | US USD formatting & v1 |
| test_risk.py::V1Checks.test_a_sixth_buy_is_blocked_three_ways | generic | test_idx_parity.py::IdxRiskParityTest.test_cash_position_duplicate_min_max_blocked_and_live | covered |
| test_risk.py::V1Checks.test_the_v2_config_blocks_buys_without_a_stop | generic | test_idx_parity.py::IdxRiskParityTest.test_stop_target_and_reward_risk_blocks | covered |
| test_risk.py::V1Checks.test_max_and_min_order | generic | test_idx_parity.py::IdxRiskParityTest.test_cash_position_duplicate_min_max_blocked_and_live | covered |
| test_risk.py::V1Checks.test_blocked_list | generic | test_idx_parity.py::IdxRiskParityTest.test_cash_position_duplicate_min_max_blocked_and_live | covered |
| test_risk.py::V1Checks.test_options_off_unless_allowed | generic | test_idx_parity.py::IdxRiskParityTest.test_format_asset_options_and_bracket_blocks | covered |
| test_risk.py::V1Checks.test_crypto_and_junk_symbols | generic | test_idx_parity.py::IdxRiskParityTest.test_format_asset_options_and_bracket_blocks | covered |
| test_risk.py::V1Checks.test_format_rules | generic | test_idx_parity.py::IdxRiskParityTest.test_format_asset_options_and_bracket_blocks | covered |
| test_risk.py::V1Checks.test_numbers_should_be_strings | generic | test_idx_parity.py::IdxRiskParityTest.test_format_asset_options_and_bracket_blocks | covered |
| test_risk.py::V1Checks.test_share_orders_need_a_price | generic | test_idx_parity.py::IdxRiskParityTest.test_format_asset_options_and_bracket_blocks | covered |
| test_risk.py::V1Checks.test_margin | generic | test_idx.py::IdxRiskTest.test_short_margin_and_fee_inclusive_loss_blocks | covered |
| test_risk.py::V1Checks.test_short_sales_are_blocked | generic | test_idx.py::IdxRiskTest.test_short_margin_and_fee_inclusive_loss_blocks | covered |
| test_risk.py::V1Checks.test_a_sell_frees_cash_for_a_later_buy | generic | test_idx_parity.py::IdxRiskParityTest.test_sell_frees_cash_and_daily_order_limit | covered |
| test_risk.py::V1Checks.test_daily_limit_and_already_placed_today | generic | test_idx_parity.py::IdxRiskParityTest.test_sell_frees_cash_and_daily_order_limit | covered |
| test_risk.py::V1Checks.test_live_account_warns | generic | test_idx_parity.py::IdxRiskParityTest.test_cash_position_duplicate_min_max_blocked_and_live | covered |
| test_risk.py::Cli.test_prices_file_freshness | generic | test_idx_parity.py::IdxRiskParityTest.test_price_freshness_lower_and_limit_ref | covered |
| test_risk.py::Cli.test_v1_orders_with_a_v1_config_file | US-only | - | US v1 USD orders |
| test_risk.py::Cli.test_errors_are_one_line | generic | test_idx_parity.py::IdxRiskParityTest.test_cli_prices_freshness_and_errors | covered |
| test_broker.py::ExplicitYes.test_plain_yes_counts | generic | test_idx_parity.py::IdxBrokerParityTest.test_explicit_yes_rules_on_idx | covered |
| test_broker.py::ExplicitYes.test_anything_else_does_not | generic | test_idx_parity.py::IdxBrokerParityTest.test_explicit_yes_rules_on_idx | covered |
| test_broker.py::ExplicitYes.test_amount_must_match_this_order | generic | test_idx_parity.py::IdxBrokerParityTest.test_explicit_yes_rules_on_idx | covered |
| test_broker.py::ExplicitYes.test_a_bracket_yes | generic | test_idx_parity.py::IdxBrokerParityTest.test_explicit_yes_rules_on_idx | covered |
| test_broker.py::TicketShape.test_tool_input_is_the_alpaca_call | US-only | - | Alpaca MCP tool shape |
| test_broker.py::TicketShape.test_the_bracket_call_leaves_out_why_and_plan | US-only | - | Alpaca bracket call shape |
| test_broker.py::TicketShape.test_plain_english | generic | test_idx_parity.py::IdxBrokerParityTest.test_fingerprint_and_plain_limit_order | covered |
| test_broker.py::DesktopConfig.test_example_is_paper_with_placeholder_keys | US-only | - | Alpaca MCP config |
| test_broker.py::Flow.test_nothing_is_ready_before_the_risk_check | generic | test_idx_parity.py::IdxBrokerParityTest.test_gates_no_risk_stale_blocked_and_decline | covered |
| test_broker.py::Flow.test_the_full_two_yes_flow | generic | test_idx.py::IdxBrokerTest.test_manual_bbca_ticket_flow_and_no_alpaca_fields | covered |
| test_broker.py::Flow.test_flatten_by_the_close | generic | test_idx_parity.py::IdxBrokerParityTest.test_flatten_end_to_end_and_explicit_qty | covered |
| test_broker.py::Flow.test_flatten_with_the_broker_qty | generic | test_idx_parity.py::IdxBrokerParityTest.test_flatten_end_to_end_and_explicit_qty | covered |
| test_broker.py::Flow.test_an_edited_order_is_not_ready | generic | test_idx.py::IdxBrokerTest.test_manual_bbca_ticket_flow_and_no_alpaca_fields | covered |
| test_broker.py::Flow.test_yesterdays_check_does_not_count | generic | test_idx_parity.py::IdxBrokerParityTest.test_gates_no_risk_stale_blocked_and_decline | covered |
| test_broker.py::Flow.test_blocked_orders_are_never_ready | generic | test_idx_parity.py::IdxBrokerParityTest.test_gates_no_risk_stale_blocked_and_decline | covered |
| test_broker.py::Flow.test_result_needs_an_approval_and_decline_is_logged | generic | test_idx_parity.py::IdxBrokerParityTest.test_gates_no_risk_stale_blocked_and_decline | covered |
| test_broker.py::Flow.test_ibkr_tickets_send_the_final_yes_to_ibkr | US-only | - | IBKR broker ticket |
| test_broker.py::Flow.test_fill_sell_relieves_the_oldest_lot | generic | test_idx_parity.py::IdxBrokerParityTest.test_fill_sell_fifo_lot_relief_and_oversell | covered |
| test_alerts.py::Calendar.test_holidays_match_the_published_list | US-only | - | NYSE holiday calendar |
| test_alerts.py::Calendar.test_daylight_saving_switches | US-only | - | US Eastern DST |
| test_alerts.py::Calendar.test_parse_now | generic | test_idx_parity.py::IdxAlertsParityTest.test_parse_now_and_quotes_offline_gz | covered |
| test_alerts.py::Calendar.test_market_status | generic | test_idx.py::IdxAlertsTest.test_idx_market_status_all_six_states_and_friday | covered |
| test_alerts.py::Quotes.test_yahoo_fixtures | generic | test_idx_parity.py::IdxAlertsParityTest.test_parse_now_and_quotes_offline_gz | covered |
| test_alerts.py::Quotes.test_stooq_fixture | US-only | - | stooq US quotes |
| test_alerts.py::Quotes.test_urls_and_user_agent | generic | test_idx_parity.py::IdxAlertsParityTest.test_network_retry_fallback_404_403_and_pause | covered |
| test_alerts.py::Quotes.test_offline_quotes_and_errors | generic | test_idx_parity.py::IdxAlertsParityTest.test_parse_now_and_quotes_offline_gz | covered |
| test_alerts.py::Quotes.test_offline_gz | generic | test_idx_parity.py::IdxAlertsParityTest.test_parse_now_and_quotes_offline_gz | covered |
| test_alerts.py::Network.test_query2_first_with_the_contract_user_agent | generic | test_idx_parity.py::IdxAlertsParityTest.test_network_retry_fallback_404_403_and_pause | covered |
| test_alerts.py::Network.test_one_retry_with_a_pause_on_429 | generic | test_idx_parity.py::IdxAlertsParityTest.test_network_retry_fallback_404_403_and_pause | covered |
| test_alerts.py::Network.test_falls_back_to_query1_on_429_and_5xx | generic | test_idx_parity.py::IdxAlertsParityTest.test_network_retry_fallback_404_403_and_pause | covered |
| test_alerts.py::Network.test_a_404_is_yahoos_answer_and_a_403_is_not_retried | generic | test_idx_parity.py::IdxAlertsParityTest.test_network_retry_fallback_404_403_and_pause | covered |
| test_alerts.py::Network.test_a_pause_between_tickers | generic | test_idx_parity.py::IdxAlertsParityTest.test_network_retry_fallback_404_403_and_pause | covered |
| test_alerts.py::Rules.test_a_target_rings_once | generic | test_idx_parity.py::IdxAlertsParityTest.test_rules_above_stop_rearm_pct_move_and_bell | covered |
| test_alerts.py::Rules.test_stop_and_rearm | generic | test_idx_parity.py::IdxAlertsParityTest.test_rules_above_stop_rearm_pct_move_and_bell | covered |
| test_alerts.py::Rules.test_pct_move_from_previous_close | generic | test_idx_parity.py::IdxAlertsParityTest.test_rules_above_stop_rearm_pct_move_and_bell | covered |
| test_alerts.py::Rules.test_opening_bell_once_per_trading_day | generic | test_idx.py::IdxAlertsTest.test_opening_bell_and_flat_by_and_yahoo_only | covered |
| test_alerts.py::Rules.test_the_plan_gives_a_stop_a_target_and_flat_by_close | generic | test_idx_parity.py::IdxAlertsParityTest.test_plan_rules_flat_by_and_bad_rules | covered |
| test_alerts.py::Rules.test_flat_by_close_rings_once_per_trading_day | generic | test_idx.py::IdxAlertsTest.test_opening_bell_and_flat_by_and_yahoo_only | covered |
| test_alerts.py::Rules.test_a_time_alert_moves_with_an_early_close | generic | test_idx.py::IdxAlertsTest.test_opening_bell_and_flat_by_and_yahoo_only | covered |
| test_alerts.py::Rules.test_the_example_rules_are_valid | generic | test_idx_parity.py::IdxAlertsParityTest.test_plan_rules_flat_by_and_bad_rules | covered |
| test_alerts.py::Rules.test_bad_rules | generic | test_idx_parity.py::IdxAlertsParityTest.test_plan_rules_flat_by_and_bad_rules | covered |
| test_alerts.py::Cli.test_the_reel_trade_from_the_plan | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_plan_add_list_reset_and_check | covered |
| test_alerts.py::Cli.test_the_v1_portfolio_evening_and_morning | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_plan_add_list_reset_and_check | covered |
| test_alerts.py::Cli.test_add_time_and_target | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_add_quote_clock_and_no_rules | covered |
| test_alerts.py::Cli.test_quote_write_merges | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_add_quote_clock_and_no_rules | covered |
| test_alerts.py::Cli.test_quote_holdings_from_portfolio_and_plan | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_add_quote_clock_and_no_rules | covered |
| test_alerts.py::Cli.test_clock_exit_codes | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_add_quote_clock_and_no_rules | covered |
| test_alerts.py::Cli.test_check_without_rules | generic | test_idx_parity.py::IdxAlertsParityTest.test_cli_add_quote_clock_and_no_rules | covered |
| test_news.py::Feeds.test_yahoo_rss | generic | test_idx_parity.py::IdxNewsParityTest.test_parse_rss_times_symbol_tags_and_dedupe | covered |
| test_news.py::Feeds.test_sec_atom_8k | US-only | - | SEC EDGAR 8-K Atom feed |
| test_news.py::Feeds.test_times | generic | test_idx_parity.py::IdxNewsParityTest.test_parse_rss_times_symbol_tags_and_dedupe | covered |
| test_news.py::Feeds.test_yahoo_symbols | generic | test_idx_parity.py::IdxNewsParityTest.test_parse_rss_times_symbol_tags_and_dedupe | covered |
| test_news.py::Tagging.test_touches_and_tags | generic | test_idx_parity.py::IdxNewsParityTest.test_parse_rss_times_symbol_tags_and_dedupe | covered |
| test_news.py::Tagging.test_earnings_filings_are_tagged | US-only | - | SEC 8-K filing tags |
| test_news.py::Tagging.test_dedupe_merges_the_same_story | generic | test_idx_parity.py::IdxNewsParityTest.test_parse_rss_times_symbol_tags_and_dedupe | covered |
| test_news.py::Check.test_new_items_once_newest_first | generic | test_idx_parity.py::IdxNewsParityTest.test_cli_once_newest_first_watchlist_errors_and_state | covered |
| test_news.py::Check.test_filings_show_in_a_wider_window | US-only | - | SEC 8-K filings window |
| test_news.py::Check.test_tickers_from_watchlist_and_plan | generic | test_idx_parity.py::IdxNewsParityTest.test_cli_once_newest_first_watchlist_errors_and_state | covered |
| test_news.py::Check.test_no_tickers_is_an_error | generic | test_idx_parity.py::IdxNewsParityTest.test_cli_once_newest_first_watchlist_errors_and_state | covered |
| test_news.py::Check.test_sec_needs_a_user_agent | US-only | - | SEC_USER_AGENT header |
| test_news.py::Check.test_the_reel_tsla_morning | generic | test_idx_parity.py::IdxNewsParityTest.test_future_filter_moves_and_day_trading_tags | covered |
| test_news.py::Check.test_moves | generic | test_idx_parity.py::IdxNewsParityTest.test_future_filter_moves_and_day_trading_tags | covered |
| test_news.py::Check.test_new_york_time_follows_daylight_saving | US-only | - | US Eastern DST |
| test_news.py::Check.test_day_trading_tags | generic | test_idx_parity.py::IdxNewsParityTest.test_future_filter_moves_and_day_trading_tags | covered |
| test_news.py::Check.test_state_forgets_after_30_days | generic | test_idx_parity.py::IdxNewsParityTest.test_cli_once_newest_first_watchlist_errors_and_state | covered |
| test_core.py::CoreTest.test_a_utc_offset_matches_original_every_30_min_2026_2027 | US-only | - | US Eastern DST |
| test_core.py::CoreTest.test_b_sessions_holiday_early_close_and_regular | US-only | - | NYSE holiday & early close |
| test_core.py::CoreTest.test_c_scanner_help_from_temp_cwd | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_load_cache_and_unknown_profile | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_last_sunday_rule_for_london | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_local_utc_round_trip_and_trading_day | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_round_tick | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_from_config | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_money_formatting | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_no_second_dst_implementation_in_skills | generic | test_idx_parity.py::IdxCoreParityTest.test_core_profile_time_tick_config_money_and_scanner_help | covered |
| test_core.py::CoreTest.test_tsla_parity_between_old_usd_and_new_currency_neutral_config | US-only | - | US _usd config aliases |
| test_core.py::CoreTest.test_new_key_wins_over_usd_alias_with_notice | generic | test_idx_parity.py::IdxCoreParityTest.test_new_key_wins_over_usd_alias_on_idx | covered |
