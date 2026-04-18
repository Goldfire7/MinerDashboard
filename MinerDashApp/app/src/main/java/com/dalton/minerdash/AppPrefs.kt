package com.dalton.minerdash

import android.content.Context
import android.content.SharedPreferences

object AppPrefs {
    private const val NAME = "miner_dash_prefs"
    private const val KEY_SERVER_URL = "server_url"
    private const val KEY_WALLET = "wallet"
    private const val KEY_COIN = "coin"
    private const val KEY_CONFIGURED = "is_configured"

    private fun prefs(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun isConfigured(ctx: Context): Boolean =
        prefs(ctx).getBoolean(KEY_CONFIGURED, false)

    fun saveConfig(ctx: Context, serverUrl: String, wallet: String, coin: String) {
        prefs(ctx).edit().apply {
            putString(KEY_SERVER_URL, serverUrl.trim().trimEnd('/'))
            putString(KEY_WALLET, wallet.trim())
            putString(KEY_COIN, coin)
            putBoolean(KEY_CONFIGURED, true)
            apply()
        }
    }

    fun getServerUrl(ctx: Context): String =
        prefs(ctx).getString(KEY_SERVER_URL, "") ?: ""

    fun getWallet(ctx: Context): String =
        prefs(ctx).getString(KEY_WALLET, "") ?: ""

    fun getCoin(ctx: Context): String =
        prefs(ctx).getString(KEY_COIN, "CKB") ?: "CKB"

    fun clear(ctx: Context) {
        prefs(ctx).edit().clear().apply()
    }
}