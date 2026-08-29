package com.example.llama

import android.app.ActivityManager
import android.content.Intent
import android.content.IntentFilter
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.provider.OpenableColumns
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import kotlin.math.roundToInt

class MainActivity : AppCompatActivity() {
    private lateinit var engine: InferenceEngine
    private var engineReady = false
    private var modelFile: File? = null
    private var runJob: Job? = null

    private lateinit var deviceTv: TextView
    private lateinit var modelTv: TextView
    private lateinit var statusTv: TextView
    private lateinit var resultTv: TextView
    private lateinit var progress: ProgressBar
    private lateinit var selectModelBtn: Button
    private lateinit var modelPageBtn: Button
    private lateinit var throughputBtn: Button
    private lateinit var runAllBtn: Button
    private lateinit var run8Btn: Button
    private lateinit var run16Btn: Button
    private lateinit var run24Btn: Button
    private lateinit var run30Btn: Button
    private lateinit var cancelBtn: Button
    private lateinit var shareBtn: Button

    private lateinit var bundle: BenchBundle
    private val results = mutableListOf<RunResult>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        deviceTv = findViewById(R.id.device_info)
        modelTv = findViewById(R.id.model_status)
        statusTv = findViewById(R.id.run_status)
        resultTv = findViewById(R.id.results)
        progress = findViewById(R.id.progress)
        selectModelBtn = findViewById(R.id.select_model)
        modelPageBtn = findViewById(R.id.model_page)
        throughputBtn = findViewById(R.id.throughput)
        runAllBtn = findViewById(R.id.run_all)
        run8Btn = findViewById(R.id.run_8k)
        run16Btn = findViewById(R.id.run_16k)
        run24Btn = findViewById(R.id.run_24k)
        run30Btn = findViewById(R.id.run_30k)
        cancelBtn = findViewById(R.id.cancel)
        shareBtn = findViewById(R.id.share)

        bundle = loadBundle()
        deviceTv.text = deviceSummary()
        modelTv.text = "No model loaded"
        statusTv.text = "Benchmark bundle: ${bundle.cases.joinToString { "${it.target / 1000}k" }}"
        setModelActionsEnabled(false)
        selectModelBtn.isEnabled = false

        lifecycleScope.launch(Dispatchers.Default) {
            engine = AiChat.getInferenceEngine(applicationContext)
            engineReady = true
            withContext(Dispatchers.Main) {
                selectModelBtn.isEnabled = true
                statusTv.text = "Ready. Select the Qwen GGUF model."
            }
        }

        selectModelBtn.setOnClickListener { modelPicker.launch(arrayOf("*/*")) }
        modelPageBtn.setOnClickListener {
            startActivity(
                Intent(
                    Intent.ACTION_VIEW,
                    Uri.parse("https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/blob/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf")
                )
            )
        }
        throughputBtn.setOnClickListener { runThroughput() }
        runAllBtn.setOnClickListener { runTargets(bundle.cases.map { it.target }) }
        run8Btn.setOnClickListener { runTargets(listOf(8_000)) }
        run16Btn.setOnClickListener { runTargets(listOf(16_000)) }
        run24Btn.setOnClickListener { runTargets(listOf(24_000)) }
        run30Btn.setOnClickListener { runTargets(listOf(30_000)) }
        cancelBtn.setOnClickListener {
            runJob?.cancel()
            statusTv.text = "Cancel requested"
        }
        shareBtn.setOnClickListener { shareResults() }
    }

    private val modelPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) loadSelectedModel(uri)
    }

    private fun loadSelectedModel(uri: Uri) {
        if (!engineReady) return
        setBusy(true, "Copying model into Hive Bench storage…")
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val displayName = queryDisplayName(uri) ?: "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
                val modelsDir = File(filesDir, "models").apply { mkdirs() }
                val destination = File(modelsDir, displayName)
                if (!destination.exists() || destination.length() == 0L) {
                    contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(destination).use { output -> input.copyTo(output) }
                    } ?: error("Could not open selected model")
                }
                withContext(Dispatchers.Main) {
                    statusTv.text = "Loading ${destination.name}…"
                }
                engine.loadModel(destination.absolutePath)
                modelFile = destination
                withContext(Dispatchers.Main) {
                    modelTv.text = "${destination.name}  •  ${formatBytes(destination.length())}"
                    appendResult("MODEL READY\n${destination.absolutePath}\n")
                    setBusy(false, "Model ready. Run a benchmark.")
                    setModelActionsEnabled(true)
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    setBusy(false, "Model load failed: ${t.message}")
                    Toast.makeText(this@MainActivity, t.message ?: "Model load failed", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun runThroughput() {
        if (modelFile == null || runJob?.isActive == true) return
        setBusy(true, "Running llama.cpp device throughput benchmark…")
        runJob = lifecycleScope.launch(Dispatchers.Default) {
            try {
                val text = engine.bench(pp = 512, tg = 64, pl = 1, nr = 1)
                withContext(Dispatchers.Main) {
                    appendResult("\nDEVICE THROUGHPUT\n$text\n")
                    setBusy(false, "Throughput benchmark complete")
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) { setBusy(false, "Benchmark failed: ${t.message}") }
            }
        }
    }

    private fun runTargets(targets: List<Int>) {
        if (modelFile == null || runJob?.isActive == true) return
        val selected = bundle.cases.filter { it.target in targets }
        if (selected.isEmpty()) return

        setBusy(true, "Starting Raw vs Hive…")
        runJob = lifecycleScope.launch(Dispatchers.Default) {
            try {
                selected.forEachIndexed { index, benchCase ->
                    // Alternate order to reduce systematic thermal/order bias.
                    val modes = if (index % 2 == 0) listOf("RAW", "HIVE") else listOf("HIVE", "RAW")
                    for (mode in modes) {
                        withContext(Dispatchers.Main) {
                            statusTv.text = "${benchCase.target / 1000}k • $mode • processing"
                        }
                        val run = executeCase(benchCase, mode)
                        results.add(run)
                        withContext(Dispatchers.Main) {
                            appendResult(formatRun(run))
                            shareBtn.isEnabled = true
                        }
                        delay(1500)
                    }
                }
                withContext(Dispatchers.Main) {
                    setBusy(false, "Selected A/B run complete")
                    appendResult("\n${summaryFor(targets)}\n")
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    setBusy(false, "A/B stopped: ${t.message ?: t::class.java.simpleName}")
                    appendResult("\nSTOPPED: ${t.stackTraceToString()}\n")
                }
            }
        }
    }

    private suspend fun executeCase(benchCase: BenchCase, mode: String): RunResult {
        val prompt = if (mode == "RAW") benchCase.rawPrompt else benchCase.hivePrompt
        val promptTokens = if (mode == "RAW") benchCase.rawTokens else benchCase.hiveTokens

        // setSystemPrompt resets llama.cpp conversation/KV state before each measured run.
        engine.setSystemPrompt(bundle.systemPrompt)
        val tempStart = batteryTempC()
        val memStart = availableMemoryBytes()
        val start = SystemClock.elapsedRealtime()
        val output = StringBuilder()
        engine.sendUserPrompt(prompt, predictLength = 64).collect { token -> output.append(token) }
        val elapsed = SystemClock.elapsedRealtime() - start
        val tempEnd = batteryTempC()
        val memEnd = availableMemoryBytes()
        val text = output.toString().trim()
        val passed = text.contains(bundle.expectedCommand)

        return RunResult(
            target = benchCase.target,
            mode = mode,
            promptTokens = promptTokens,
            elapsedMs = elapsed,
            passed = passed,
            output = text,
            batteryStartC = tempStart,
            batteryEndC = tempEnd,
            availableRamStart = memStart,
            availableRamEnd = memEnd,
        )
    }

    private fun summaryFor(targets: List<Int>): String {
        val rows = targets.mapNotNull { target ->
            val raw = results.lastOrNull { it.target == target && it.mode == "RAW" }
            val hive = results.lastOrNull { it.target == target && it.mode == "HIVE" }
            if (raw == null || hive == null) return@mapNotNull null
            val reduction = if (raw.promptTokens > 0) {
                (100.0 * (raw.promptTokens - hive.promptTokens) / raw.promptTokens)
            } else 0.0
            "${target / 1000}k: Raw=${if (raw.passed) "PASS" else "FAIL"} ${raw.elapsedMs}ms | " +
                "Hive=${if (hive.passed) "PASS" else "FAIL"} ${hive.elapsedMs}ms | " +
                "tokens ${raw.promptTokens}→${hive.promptTokens} (${String.format("%.1f", reduction)}% less)"
        }
        return "A/B SUMMARY\n" + rows.joinToString("\n")
    }

    private fun formatRun(run: RunResult): String = buildString {
        append("\n${run.target / 1000}k ${run.mode}: ${if (run.passed) "PASS" else "FAIL"}\n")
        append("prompt=${run.promptTokens} tokens • elapsed=${run.elapsedMs} ms")
        if (run.batteryStartC != null && run.batteryEndC != null) {
            append(" • battery=${run.batteryStartC}→${run.batteryEndC}°C")
        }
        append("\n")
        append(run.output.take(1200))
        append("\n")
    }

    private fun setBusy(busy: Boolean, message: String) {
        progress.visibility = if (busy) android.view.View.VISIBLE else android.view.View.GONE
        statusTv.text = message
        selectModelBtn.isEnabled = !busy && engineReady
        modelPageBtn.isEnabled = !busy
        cancelBtn.isEnabled = busy
        if (modelFile != null) setModelActionsEnabled(!busy)
    }

    private fun setModelActionsEnabled(enabled: Boolean) {
        throughputBtn.isEnabled = enabled
        runAllBtn.isEnabled = enabled
        run8Btn.isEnabled = enabled
        run16Btn.isEnabled = enabled
        run24Btn.isEnabled = enabled
        run30Btn.isEnabled = enabled
        shareBtn.isEnabled = enabled && results.isNotEmpty()
    }

    private fun appendResult(text: String) {
        resultTv.append(text)
    }

    private fun shareResults() {
        if (results.isEmpty()) return
        val root = JSONObject()
        root.put("schema", "hive.phone-bench-result.v1")
        root.put("device", deviceSummary())
        root.put("model", modelFile?.name ?: "unknown")
        root.put("benchmark", bundle.benchmark)
        root.put("expected_command", bundle.expectedCommand)
        val array = JSONArray()
        results.forEach { run ->
            array.put(JSONObject().apply {
                put("target", run.target)
                put("mode", run.mode)
                put("prompt_tokens", run.promptTokens)
                put("elapsed_ms", run.elapsedMs)
                put("passed", run.passed)
                put("output", run.output)
                put("battery_start_c", run.batteryStartC)
                put("battery_end_c", run.batteryEndC)
                put("available_ram_start", run.availableRamStart)
                put("available_ram_end", run.availableRamEnd)
            })
        }
        root.put("runs", array)
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "application/json"
            putExtra(Intent.EXTRA_SUBJECT, "Hive Bench phone result")
            putExtra(Intent.EXTRA_TEXT, root.toString(2))
        }
        startActivity(Intent.createChooser(intent, "Share Hive Bench result"))
    }

    private fun loadBundle(): BenchBundle {
        val root = JSONObject(assets.open("hive_bench_cases.json").bufferedReader().use { it.readText() })
        val array = root.getJSONArray("cases")
        val cases = buildList {
            for (i in 0 until array.length()) {
                val c = array.getJSONObject(i)
                add(
                    BenchCase(
                        target = c.getInt("target"),
                        rawPrompt = c.getString("raw_prompt"),
                        hivePrompt = c.getString("hive_prompt"),
                        rawTokens = c.getInt("raw_tokens"),
                        hiveTokens = c.getInt("hive_tokens"),
                    )
                )
            }
        }
        return BenchBundle(
            benchmark = root.getString("benchmark"),
            expectedCommand = root.getString("expected_command"),
            systemPrompt = root.getString("system_prompt"),
            cases = cases,
        )
    }

    private fun queryDisplayName(uri: Uri): String? {
        var cursor: Cursor? = null
        return try {
            cursor = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            if (cursor != null && cursor.moveToFirst()) cursor.getString(0) else null
        } finally {
            cursor?.close()
        }
    }

    private fun deviceSummary(): String {
        val activityManager = getSystemService(ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo().also { activityManager.getMemoryInfo(it) }
        return "${Build.MANUFACTURER} ${Build.MODEL} • Android ${Build.VERSION.RELEASE} • " +
            "${Runtime.getRuntime().availableProcessors()} CPUs • RAM ${formatBytes(info.totalMem)}"
    }

    private fun availableMemoryBytes(): Long {
        val activityManager = getSystemService(ACTIVITY_SERVICE) as ActivityManager
        return ActivityManager.MemoryInfo().also { activityManager.getMemoryInfo(it) }.availMem
    }

    private fun batteryTempC(): Double? {
        val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val tenths = intent.getIntExtra(android.os.BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
        return if (tenths == Int.MIN_VALUE) null else tenths / 10.0
    }

    private fun formatBytes(bytes: Long): String {
        if (bytes <= 0) return "0 B"
        val gib = bytes / (1024.0 * 1024.0 * 1024.0)
        return if (gib >= 1.0) String.format("%.1f GiB", gib) else "${(bytes / 1048576.0).roundToInt()} MiB"
    }

    override fun onDestroy() {
        runJob?.cancel()
        if (engineReady) engine.destroy()
        super.onDestroy()
    }
}

data class BenchCase(
    val target: Int,
    val rawPrompt: String,
    val hivePrompt: String,
    val rawTokens: Int,
    val hiveTokens: Int,
)

data class BenchBundle(
    val benchmark: String,
    val expectedCommand: String,
    val systemPrompt: String,
    val cases: List<BenchCase>,
)

data class RunResult(
    val target: Int,
    val mode: String,
    val promptTokens: Int,
    val elapsedMs: Long,
    val passed: Boolean,
    val output: String,
    val batteryStartC: Double?,
    val batteryEndC: Double?,
    val availableRamStart: Long,
    val availableRamEnd: Long,
)
