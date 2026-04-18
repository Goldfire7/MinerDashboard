package com.dalton.minerdash

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.Spinner
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class SetupActivity : AppCompatActivity() {

    private lateinit var editServerUrl: EditText
    private lateinit var editWallet: EditText
    private lateinit var spinnerCoin: Spinner
    private lateinit var textStatus: TextView
    private lateinit var btnConnect: Button
    private lateinit var progressBar: ProgressBar

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // If already configured, skip to main
        if (AppPrefs.isConfigured(this)) {
            startMain()
            return
        }

        setContentView(R.layout.activity_setup)

        editServerUrl = findViewById(R.id.editServerUrl)
        editWallet = findViewById(R.id.editWallet)
        spinnerCoin = findViewById(R.id.spinnerCoin)
        textStatus = findViewById(R.id.textStatus)
        btnConnect = findViewById(R.id.btnConnect)
        progressBar = findViewById(R.id.progressBar)

        setupCoinSpinner()
        btnConnect.setOnClickListener { attemptConnect() }
    }

    private fun setupCoinSpinner() {
        val coins = listOf("CKB", "ETH", "BTC", "LTC", "DOGE", "KAS")
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, coins)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spinnerCoin.adapter = adapter
        spinnerCoin.setSelection(0) // default CKB
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun attemptConnect() {
        val serverUrl = editServerUrl.text.toString().trim()
        val wallet = editWallet.text.toString().trim()
        val coin = spinnerCoin.selectedItem.toString()

        if (serverUrl.isEmpty()) {
            showError("Please enter a dashboard URL")
            return
        }

        if (!serverUrl.startsWith("http://") && !serverUrl.startsWith("https://")) {
            showError("URL must start with http:// or https://")
            return
        }

        showLoading(true)
        textStatus.visibility = View.GONE

        // Test connection by fetching /api/config
        Thread {
            try {
                val testUrl = if (serverUrl.endsWith("/")) serverUrl else "$serverUrl/"
                val request = Request.Builder()
                    .url("${testUrl}api/config")
                    .build()

                val response = httpClient.newCall(request).execute()
                val body = response.body?.string() ?: throw Exception("Empty response")

                // Validate it's a config response
                val json = JSONObject(body)
                val hasMiners = json.has("miners") || json.has("wallet")

                if (response.code == 200 && hasMiners) {
                    runOnUiThread {
                        AppPrefs.saveConfig(this, serverUrl, wallet, coin)
                        startMain()
                    }
                } else {
                    runOnUiThread {
                        showError("Dashboard not recognized. Check the URL.")
                        showLoading(false)
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    showError("Connection failed: ${e.message}")
                    showLoading(false)
                }
            }
        }.start()
    }

    private fun showError(msg: String) {
        textStatus.text = msg
        textStatus.visibility = View.VISIBLE
    }

    private fun showLoading(show: Boolean) {
        progressBar.visibility = if (show) View.VISIBLE else View.GONE
        btnConnect.isEnabled = !show
        btnConnect.alpha = if (show) 0.5f else 1f
    }

    private fun startMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}