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
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
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
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import kotlin.math.roundToInt

class MainActivity : AppCompatActivity() {
    private lateinit var engine: InferenceEngine
    private var engineReady = false
    private var modelFile: File? = null
    private var runJob: Job? = null

    private lateinit var deviceTv: TextView
    private lateinit var modelTv: TextView
    private lateinit var statusTv: TextView
    private lateinit var progress: ProgressBar

    private lateinit var selectModelBtn: Button
    private lateinit var modelPageBtn: Button
    private lateinit var navChatBtn: Button
    private lateinit var navWorkBtn: Button
    private lateinit var navMemoryBtn: Button
    private lateinit var navDiagBtn: Button

    private lateinit var chatPanel: LinearLayout
    private lateinit var chatLogTv: TextView
    private lateinit var hiveStateTv: TextView
    private lateinit var chatInput: EditText
    private lateinit var sendChatBtn: Button
    private lateinit var clearChatBtn: Button

    private lateinit var memoryPanel: LinearLayout
    private lateinit var memoryStateEdit: EditText
    private lateinit var memorySourcesTv: TextView
    private lateinit var saveMemoryBtn: Button
    private lateinit var rebuildMemoryBtn: Button
    private lateinit var clearMemoryBtn: Button

    private lateinit var workPanel: LinearLayout
    private lateinit var projectStatusTv: TextView
    private lateinit var importZipBtn: Button
    private lateinit var exportZipBtn: Button
    private lateinit var taskInput: EditText
    private lateinit var planTaskBtn: Button
    private lateinit var proposeChangeBtn: Button
    private lateinit var workOutputTv: TextView
    private lateinit var applyChangeBtn: Button
    private lateinit var rejectChangeBtn: Button
    private lateinit var undoChangeBtn: Button
    private lateinit var clearWorkspaceBtn: Button

    private lateinit var diagPanel: LinearLayout
    private lateinit var resultTv: TextView
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
    private val chatMessages = mutableListOf<ChatMessage>()
    private var hiveStateCapsule = "{}"
    private var workPlan = ""
    private var projectName = ""
    private var pendingProposal: WorkspaceProposal? = null

    private val prefs by lazy { getSharedPreferences("hive_mobile", MODE_PRIVATE) }
    private val workspaceDir by lazy { File(filesDir, "workspace") }
    private val auditFile by lazy { File(filesDir, "hive_work_audit.jsonl") }
    private val undoDir by lazy { File(filesDir, "workspace_undo") }
    private val lastUndoFile by lazy { File(filesDir, "workspace_last_undo.json") }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        bindViews()
        bundle = loadBundle()
        restorePersistentState()
        renderChat()
        renderMemory()
        renderProjectStatus()
        showPanel("chat")

        deviceTv.text = deviceSummary()
        modelTv.text = "No model loaded"
        statusTv.text = "Initializing local llama.cpp engine…"
        setModelActionsEnabled(false)
        selectModelBtn.isEnabled = false

        lifecycleScope.launch(Dispatchers.Default) {
            engine = AiChat.getInferenceEngine(applicationContext)
            engineReady = true
            val remembered = prefs.getString("last_model_path", null)?.let(::File)
            if (remembered?.isFile == true && remembered.length() in 1..MAX_MODEL_BYTES) {
                try {
                    engine.loadModel(remembered.absolutePath)
                    modelFile = remembered
                    withContext(Dispatchers.Main) {
                        selectModelBtn.isEnabled = true
                        modelTv.text = "${remembered.name} • ${formatBytes(remembered.length())}"
                        statusTv.text = "Local model restored automatically."
                        setModelActionsEnabled(true)
                    }
                } catch (t: Throwable) {
                    prefs.edit().remove("last_model_path").apply()
                    withContext(Dispatchers.Main) {
                        selectModelBtn.isEnabled = true
                        statusTv.text = "Saved model could not be restored: ${t.message}"
                    }
                }
            } else {
                withContext(Dispatchers.Main) {
                    selectModelBtn.isEnabled = true
                    statusTv.text = "Ready. Load Qwen2.5-Coder 3B Q4_K_M to start."
                }
            }
        }

        wireActions()
    }

    private fun bindViews() {
        deviceTv = findViewById(R.id.device_info)
        modelTv = findViewById(R.id.model_status)
        statusTv = findViewById(R.id.run_status)
        progress = findViewById(R.id.progress)
        selectModelBtn = findViewById(R.id.select_model)
        modelPageBtn = findViewById(R.id.model_page)
        navChatBtn = findViewById(R.id.nav_chat)
        navWorkBtn = findViewById(R.id.nav_work)
        navMemoryBtn = findViewById(R.id.nav_memory)
        navDiagBtn = findViewById(R.id.nav_diag)

        chatPanel = findViewById(R.id.chat_panel)
        chatLogTv = findViewById(R.id.chat_log)
        hiveStateTv = findViewById(R.id.hive_state_status)
        chatInput = findViewById(R.id.chat_input)
        sendChatBtn = findViewById(R.id.send_chat)
        clearChatBtn = findViewById(R.id.clear_chat)

        memoryPanel = findViewById(R.id.memory_panel)
        memoryStateEdit = findViewById(R.id.memory_state_edit)
        memorySourcesTv = findViewById(R.id.memory_sources)
        saveMemoryBtn = findViewById(R.id.save_memory)
        rebuildMemoryBtn = findViewById(R.id.rebuild_memory)
        clearMemoryBtn = findViewById(R.id.clear_memory)

        workPanel = findViewById(R.id.work_panel)
        projectStatusTv = findViewById(R.id.project_status)
        importZipBtn = findViewById(R.id.import_zip)
        exportZipBtn = findViewById(R.id.export_zip)
        taskInput = findViewById(R.id.task_input)
        planTaskBtn = findViewById(R.id.plan_task)
        proposeChangeBtn = findViewById(R.id.propose_change)
        workOutputTv = findViewById(R.id.work_output)
        applyChangeBtn = findViewById(R.id.apply_change)
        rejectChangeBtn = findViewById(R.id.reject_change)
        undoChangeBtn = findViewById(R.id.undo_change)
        clearWorkspaceBtn = findViewById(R.id.clear_workspace)

        diagPanel = findViewById(R.id.diag_panel)
        resultTv = findViewById(R.id.results)
        throughputBtn = findViewById(R.id.throughput)
        runAllBtn = findViewById(R.id.run_all)
        run8Btn = findViewById(R.id.run_8k)
        run16Btn = findViewById(R.id.run_16k)
        run24Btn = findViewById(R.id.run_24k)
        run30Btn = findViewById(R.id.run_30k)
        cancelBtn = findViewById(R.id.cancel)
        shareBtn = findViewById(R.id.share)
    }

    private fun wireActions() {
        selectModelBtn.setOnClickListener { modelPicker.launch(arrayOf("*/*")) }
        modelPageBtn.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(QWEN_MODEL_URL)))
        }

        navChatBtn.setOnClickListener { showPanel("chat") }
        navWorkBtn.setOnClickListener { showPanel("work") }
        navMemoryBtn.setOnClickListener { showPanel("memory"); renderMemory() }
        navDiagBtn.setOnClickListener { showPanel("diag") }

        sendChatBtn.setOnClickListener { sendChat() }
        clearChatBtn.setOnClickListener {
            chatMessages.clear()
            hiveStateCapsule = "{}"
            saveChatState()
            renderChat()
            statusTv.text = "Chat source history and derived Hive state cleared."
        }
        saveMemoryBtn.setOnClickListener { saveEditedMemory() }
        rebuildMemoryBtn.setOnClickListener { rebuildMemoryFromSource() }
        clearMemoryBtn.setOnClickListener { clearDerivedMemory() }

        importZipBtn.setOnClickListener { zipPicker.launch(arrayOf("application/zip", "application/octet-stream")) }
        exportZipBtn.setOnClickListener {
            if (workspaceHasFiles()) exportZipLauncher.launch("${safeProjectName()}-hive.zip")
        }
        planTaskBtn.setOnClickListener { planWorkTask() }
        proposeChangeBtn.setOnClickListener { proposeWorkspaceChange() }
        applyChangeBtn.setOnClickListener { applyWorkspaceProposal() }
        rejectChangeBtn.setOnClickListener { rejectWorkspaceProposal() }
        undoChangeBtn.setOnClickListener { undoLastWorkspaceChange() }
        clearWorkspaceBtn.setOnClickListener { clearWorkspace() }

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

    private fun showPanel(panel: String) {
        chatPanel.visibility = if (panel == "chat") View.VISIBLE else View.GONE
        memoryPanel.visibility = if (panel == "memory") View.VISIBLE else View.GONE
        workPanel.visibility = if (panel == "work") View.VISIBLE else View.GONE
        diagPanel.visibility = if (panel == "diag") View.VISIBLE else View.GONE
    }

    private val modelPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) loadSelectedModel(uri)
    }

    private val zipPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importWorkspaceZip(uri)
    }

    private val exportZipLauncher = registerForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        if (uri != null) exportWorkspaceZip(uri)
    }

    private fun loadSelectedModel(uri: Uri) {
        if (!engineReady) return
        val sourceSize = queryFileSize(uri)
        if (sourceSize != null && sourceSize > MAX_MODEL_BYTES) {
            Toast.makeText(this, "That model is too large for Hive Mobile v0.2. Use Qwen2.5-Coder 3B Q4_K_M (~2.1 GB).", Toast.LENGTH_LONG).show()
            statusTv.text = "Model rejected: too large for the mobile baseline."
            return
        }

        setBusy(true, "Copying local model into Hive storage…")
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
                if (destination.length() > MAX_MODEL_BYTES) {
                    destination.delete()
                    error("Model exceeds the Hive Mobile baseline size. Use Qwen2.5-Coder 3B Q4_K_M.")
                }
                withContext(Dispatchers.Main) { statusTv.text = "Loading ${destination.name}…" }
                engine.loadModel(destination.absolutePath)
                modelFile = destination
                prefs.edit().putString("last_model_path", destination.absolutePath).apply()
                withContext(Dispatchers.Main) {
                    modelTv.text = "${destination.name} • ${formatBytes(destination.length())}"
                    setBusy(false, "Model ready. Chat, work, or run diagnostics.")
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

    // ---------------- CHAT ----------------

    private fun sendChat() {
        val text = chatInput.text.toString().trim()
        if (text.isEmpty() || modelFile == null || runJob?.isActive == true) return

        val userMessage = ChatMessage(nextMessageId(), "user", text, System.currentTimeMillis())
        chatMessages.add(userMessage)
        saveChatState()
        chatInput.setText("")
        renderChat()
        setBusy(true, "Hive is thinking from compact state + recent exact source…")

        runJob = lifecycleScope.launch(Dispatchers.Default) {
            try {
                engine.setSystemPrompt(CHAT_SYSTEM_PROMPT)
                val prompt = buildChatPrompt()
                val answer = collectModel(prompt, 512)
                chatMessages.add(ChatMessage(nextMessageId(), "assistant", answer, System.currentTimeMillis()))
                saveChatState()
                withContext(Dispatchers.Main) { renderChat() }

                withContext(Dispatchers.Main) { statusTv.text = "Updating derived Hive state…" }
                refreshHiveStateCapsule()
                saveChatState()
                withContext(Dispatchers.Main) {
                    renderChat()
                    setBusy(false, "Ready")
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    setBusy(false, "Chat stopped: ${t.message ?: t::class.java.simpleName}")
                }
            }
        }
    }

    private suspend fun refreshHiveStateCapsule() {
        engine.setSystemPrompt(STATE_EXTRACTOR_SYSTEM_PROMPT)
        val recent = chatMessages.takeLast(10).joinToString("\n") {
            "[${it.id}] ${it.role.uppercase()}: ${it.text}"
        }
        val prompt = """
CURRENT DERIVED STATE:
$hiveStateCapsule

NEW SOURCE EVIDENCE (exact, source-linked):
$recent

Return the updated compact state JSON only.
""".trimIndent()
        val candidate = collectModel(prompt, 320).trim()
        val json = extractJsonObject(candidate)
        if (json != null) hiveStateCapsule = json
    }

    private fun buildChatPrompt(): String {
        val recent = chatMessages.takeLast(8).joinToString("\n") {
            "[${it.id}] ${it.role.uppercase()}: ${it.text}"
        }
        return """
HIVE CURRENT MACHINE STATE (derived interpretation; source text remains authoritative):
$hiveStateCapsule

RECENT EXACT SOURCE MESSAGES:
$recent

Respond to the newest USER message. Do not claim access to anything not present here or in the active workspace.
""".trimIndent()
    }

    private fun renderChat() {
        val display = chatMessages.takeLast(24).joinToString("\n\n") {
            val who = if (it.role == "user") "You" else "Hive"
            "$who: ${it.text}"
        }
        chatLogTv.text = if (display.isBlank()) "Local conversation starts here. Exact messages are stored on-device." else display
        val sourceCount = chatMessages.size
        val stateSize = hiveStateCapsule.length
        hiveStateTv.text = "Hive state: $stateSize chars derived • exact source messages: $sourceCount"
        renderMemory()
    }

    private fun renderMemory() {
        if (!::memoryStateEdit.isInitialized) return
        memoryStateEdit.setText(hiveStateCapsule)
        memorySourcesTv.text = if (chatMessages.isEmpty()) {
            "No exact source messages yet. Derived memory never replaces source text."
        } else {
            chatMessages.takeLast(40).joinToString("\n\n") { message ->
                val who = if (message.role == "user") "USER" else "HIVE"
                "${message.id} • $who\n${message.text.take(240)}"
            }
        }
    }

    private fun saveEditedMemory() {
        val candidate = memoryStateEdit.text.toString().trim().ifBlank { "{}" }
        try {
            val parsed = JSONObject(candidate)
            hiveStateCapsule = parsed.toString(2)
            saveChatState()
            renderMemory()
            statusTv.text = "Derived Hive state updated. Exact source messages unchanged."
        } catch (t: Throwable) {
            statusTv.text = "Memory not saved: state must be a JSON object."
        }
    }

    private fun rebuildMemoryFromSource() {
        if (modelFile == null || chatMessages.isEmpty() || runJob?.isActive == true) return
        setBusy(true, "Rebuilding derived state from exact source messages…")
        runJob = lifecycleScope.launch(Dispatchers.Default) {
            try {
                hiveStateCapsule = "{}"
                refreshHiveStateCapsule()
                saveChatState()
                withContext(Dispatchers.Main) {
                    renderMemory()
                    setBusy(false, "Derived state rebuilt from source.")
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) { setBusy(false, "Memory rebuild stopped: ${t.message}") }
            }
        }
    }

    private fun clearDerivedMemory() {
        hiveStateCapsule = "{}"
        saveChatState()
        renderMemory()
        statusTv.text = "Derived Hive state cleared. Exact source messages preserved."
    }

    private fun nextMessageId(): String = "m${chatMessages.size + 1}"

    private fun saveChatState() {
        val array = JSONArray()
        chatMessages.forEach { message ->
            array.put(JSONObject().apply {
                put("id", message.id)
                put("role", message.role)
                put("text", message.text)
                put("created_at", message.createdAt)
            })
        }
        prefs.edit()
            .putString("chat_messages", array.toString())
            .putString("hive_state", hiveStateCapsule)
            .apply()
    }

    // ---------------- WORK ----------------

    private fun importWorkspaceZip(uri: Uri) {
        if (runJob?.isActive == true) return
        setBusy(true, "Importing project into isolated Hive workspace…")
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                workspaceDir.deleteRecursively()
                undoDir.deleteRecursively()
                lastUndoFile.delete()
                workspaceDir.mkdirs()
                var entries = 0
                var totalBytes = 0L
                ZipInputStream(contentResolver.openInputStream(uri) ?: error("Could not open ZIP")).use { zip ->
                    while (true) {
                        val entry = zip.nextEntry ?: break
                        if (++entries > MAX_ZIP_ENTRIES) error("ZIP has too many entries")
                        val out = File(workspaceDir, entry.name)
                        val rootPath = workspaceDir.canonicalPath + File.separator
                        if (!out.canonicalPath.startsWith(rootPath)) error("Unsafe ZIP path: ${entry.name}")
                        if (entry.isDirectory) {
                            out.mkdirs()
                        } else {
                            out.parentFile?.mkdirs()
                            FileOutputStream(out).use { output ->
                                val buffer = ByteArray(8192)
                                while (true) {
                                    val read = zip.read(buffer)
                                    if (read <= 0) break
                                    totalBytes += read
                                    if (totalBytes > MAX_WORKSPACE_BYTES) error("Workspace exceeds ${formatBytes(MAX_WORKSPACE_BYTES)}")
                                    output.write(buffer, 0, read)
                                }
                            }
                        }
                        zip.closeEntry()
                    }
                }
                projectName = (queryDisplayName(uri) ?: "workspace.zip").removeSuffix(".zip")
                workPlan = ""
                pendingProposal = null
                prefs.edit().putString("project_name", projectName).putString("work_plan", "").apply()
                withContext(Dispatchers.Main) {
                    renderProjectStatus()
                    workOutputTv.text = "Imported $entries ZIP entries into app-private workspace.\nNothing outside this workspace will be modified."
                    setBusy(false, "Workspace ready")
                    setModelActionsEnabled(modelFile != null)
                }
            } catch (t: Throwable) {
                workspaceDir.deleteRecursively()
                withContext(Dispatchers.Main) {
                    renderProjectStatus()
                    setBusy(false, "Import failed: ${t.message}")
                }
            }
        }
    }

    private fun planWorkTask() {
        val task = taskInput.text.toString().trim()
        if (task.isEmpty() || modelFile == null || !workspaceHasFiles() || runJob?.isActive == true) return
        prefs.edit().putString("work_task", task).apply()
        setBusy(true, "Hive is mapping the workspace and planning…")
        runJob = lifecycleScope.launch(Dispatchers.Default) {
            try {
                engine.setSystemPrompt(WORK_PLAN_SYSTEM_PROMPT)
                val prompt = """
EXACT HUMAN TASK:
$task

WORKSPACE MANIFEST:
${workspaceManifest()}

RELEVANT SOURCE EVIDENCE:
${relevantWorkspaceContext(task, maxFiles = 6, maxTotalChars = 24_000)}

Produce a conservative plan. Do not claim any file was changed.
""".trimIndent()
                workPlan = collectModel(prompt, 650)
                prefs.edit().putString("work_plan", workPlan).apply()
                withContext(Dispatchers.Main) {
                    workOutputTv.text = "PLAN\n$workPlan"
                    setBusy(false, "Plan ready. Review it, then request a proposed change.")
                    setModelActionsEnabled(true)
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) { setBusy(false, "Planning stopped: ${t.message}") }
            }
        }
    }

    private fun proposeWorkspaceChange() {
        val task = taskInput.text.toString().trim()
        if (task.isEmpty() || workPlan.isBlank() || modelFile == null || !workspaceHasFiles() || runJob?.isActive == true) return
        pendingProposal = null
        setBusy(true, "Generating one isolated proposed file replacement…")
        runJob = lifecycleScope.launch(Dispatchers.Default) {
            try {
                engine.setSystemPrompt(WORK_CHANGE_SYSTEM_PROMPT)
                val prompt = """
EXACT HUMAN TASK:
$task

APPROVED PLAN CONTEXT (not yet executed):
$workPlan

KNOWN FILES:
${workspaceManifest()}

SOURCE FILES (exact current workspace text):
${relevantWorkspaceContext(task + " " + workPlan, maxFiles = 8, maxTotalChars = 42_000)}

Return exactly one JSON object with target_file, reason, replacement.
""".trimIndent()
                val raw = collectModel(prompt, 3072)
                val proposal = parseWorkspaceProposal(raw)
                pendingProposal = proposal
                withContext(Dispatchers.Main) {
                    renderProposal(proposal)
                    setBusy(false, "Proposal ready. Nothing has been written yet.")
                    setModelActionsEnabled(true)
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    setBusy(false, "Proposal rejected by Hive guardrails: ${t.message}")
                }
            }
        }
    }

    private fun parseWorkspaceProposal(raw: String): WorkspaceProposal {
        val jsonText = extractJsonObject(raw) ?: error("Model did not return a JSON proposal")
        val obj = JSONObject(jsonText)
        val target = obj.optString("target_file").trim().replace('\\', '/')
        val reason = obj.optString("reason").trim()
        val replacement = obj.optString("replacement")
        if (target.isBlank()) error("Proposal missing target_file")
        if (replacement.isBlank()) error("Proposal replacement is empty")
        if (replacement.length > MAX_REPLACEMENT_CHARS) error("Replacement is too large for mobile review")
        val targetFile = safeWorkspaceFile(target)
        if (!targetFile.isFile) error("Unknown target file: $target")
        if (target !in workspaceFiles().map { relativeWorkspacePath(it) }.toSet()) error("Target is not in current workspace manifest")
        return WorkspaceProposal(target, reason.ifBlank { "Model proposed a local file replacement." }, replacement)
    }

    private fun renderProposal(proposal: WorkspaceProposal) {
        val target = safeWorkspaceFile(proposal.targetFile)
        val oldText = target.readText(Charsets.UTF_8)
        val oldLines = oldText.lines().size
        val newLines = proposal.replacement.lines().size
        workOutputTv.text = buildString {
            append("PROPOSED — NOT APPLIED\n")
            append("Target: ${proposal.targetFile}\n")
            append("Reason: ${proposal.reason}\n")
            append("Lines: $oldLines → $newLines\n")
            append("Old SHA-256: ${sha256(oldText).take(16)}…\n")
            append("New SHA-256: ${sha256(proposal.replacement).take(16)}…\n\n")
            append("Replacement preview:\n")
            append(proposal.replacement.take(3000))
            if (proposal.replacement.length > 3000) append("\n…preview truncated…")
        }
    }

    private fun applyWorkspaceProposal() {
        val proposal = pendingProposal ?: return
        try {
            val target = safeWorkspaceFile(proposal.targetFile)
            val oldText = target.readText(Charsets.UTF_8)
            createUndoCheckpoint(proposal, oldText)
            target.writeText(proposal.replacement, Charsets.UTF_8)
            appendAudit("applied", proposal, oldText)
            pendingProposal = null
            workOutputTv.text = "APPLIED TO ISOLATED WORKSPACE\n${proposal.targetFile}\n\nExport the workspace ZIP when ready."
            statusTv.text = "Change applied inside Hive workspace only."
            setModelActionsEnabled(modelFile != null)
        } catch (t: Throwable) {
            statusTv.text = "Apply failed: ${t.message}"
        }
    }

    private fun rejectWorkspaceProposal() {
        val proposal = pendingProposal ?: return
        appendAudit("rejected", proposal, null)
        pendingProposal = null
        workOutputTv.text = "Proposal rejected. Workspace unchanged."
        statusTv.text = "Proposal rejected"
        setModelActionsEnabled(modelFile != null)
    }

    private fun createUndoCheckpoint(proposal: WorkspaceProposal, oldText: String) {
        undoDir.mkdirs()
        val backup = File(undoDir, "${System.currentTimeMillis()}.bak")
        backup.writeText(oldText, Charsets.UTF_8)
        val meta = JSONObject().apply {
            put("target_file", proposal.targetFile)
            put("backup_path", backup.absolutePath)
            put("expected_current_sha256", sha256(proposal.replacement))
            put("created_at", System.currentTimeMillis())
        }
        lastUndoFile.writeText(meta.toString(), Charsets.UTF_8)
        undoChangeBtn.isEnabled = true
    }

    private fun undoLastWorkspaceChange() {
        if (!lastUndoFile.isFile) {
            statusTv.text = "Nothing to undo"
            return
        }
        try {
            val meta = JSONObject(lastUndoFile.readText(Charsets.UTF_8))
            val targetFile = meta.getString("target_file")
            val target = safeWorkspaceFile(targetFile)
            val backup = File(meta.getString("backup_path"))
            if (!target.isFile || !backup.isFile) error("Undo checkpoint is incomplete")
            val current = target.readText(Charsets.UTF_8)
            val expected = meta.getString("expected_current_sha256")
            if (sha256(current) != expected) error("File changed after the checkpoint; refusing unsafe undo")
            val restored = backup.readText(Charsets.UTF_8)
            target.writeText(restored, Charsets.UTF_8)
            auditFile.appendText(JSONObject().apply {
                put("timestamp", System.currentTimeMillis())
                put("disposition", "undone")
                put("project", projectName)
                put("target_file", targetFile)
                put("restored_sha256", sha256(restored))
            }.toString() + "\n", Charsets.UTF_8)
            backup.delete()
            lastUndoFile.delete()
            undoChangeBtn.isEnabled = false
            workOutputTv.text = "UNDONE\n$targetFile restored to its pre-apply contents."
            statusTv.text = "Last applied workspace change undone"
        } catch (t: Throwable) {
            statusTv.text = "Undo refused: ${t.message}"
        }
    }

    private fun appendAudit(disposition: String, proposal: WorkspaceProposal, oldText: String?) {
        val record = JSONObject().apply {
            put("timestamp", System.currentTimeMillis())
            put("disposition", disposition)
            put("project", projectName)
            put("task", taskInput.text.toString())
            put("target_file", proposal.targetFile)
            put("reason", proposal.reason)
            put("old_sha256", oldText?.let { sha256(it) })
            put("new_sha256", sha256(proposal.replacement))
        }
        auditFile.appendText(record.toString() + "\n", Charsets.UTF_8)
    }

    private fun clearWorkspace() {
        if (runJob?.isActive == true) return
        workspaceDir.deleteRecursively()
        undoDir.deleteRecursively()
        lastUndoFile.delete()
        projectName = ""
        workPlan = ""
        pendingProposal = null
        taskInput.setText("")
        workOutputTv.text = ""
        prefs.edit().remove("project_name").remove("work_plan").remove("work_task").apply()
        renderProjectStatus()
        setModelActionsEnabled(modelFile != null)
        statusTv.text = "Workspace cleared"
    }

    private fun renderProjectStatus() {
        val files = workspaceFiles()
        val bytes = files.sumOf { it.length() }
        projectStatusTv.text = if (files.isEmpty()) {
            "No workspace imported. Import a project ZIP; Hive edits only its private copy."
        } else {
            "${projectName.ifBlank { "Workspace" }} • ${files.size} files • ${formatBytes(bytes)} • isolated app storage"
        }
        exportZipBtn.isEnabled = files.isNotEmpty()
        undoChangeBtn.isEnabled = files.isNotEmpty() && lastUndoFile.isFile
    }

    private fun exportWorkspaceZip(uri: Uri) {
        if (!workspaceHasFiles()) return
        setBusy(true, "Exporting isolated workspace ZIP…")
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val output = contentResolver.openOutputStream(uri) ?: error("Could not create export")
                ZipOutputStream(output).use { zip ->
                    workspaceFiles().forEach { file ->
                        val entry = ZipEntry(relativeWorkspacePath(file))
                        zip.putNextEntry(entry)
                        FileInputStream(file).use { input -> input.copyTo(zip) }
                        zip.closeEntry()
                    }
                }
                withContext(Dispatchers.Main) { setBusy(false, "Workspace exported") }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) { setBusy(false, "Export failed: ${t.message}") }
            }
        }
    }

    private fun workspaceManifest(): String {
        val files = workspaceFiles().take(MAX_MANIFEST_FILES)
        return files.joinToString("\n") { "- ${relativeWorkspacePath(it)} (${it.length()} bytes)" }
    }

    private fun relevantWorkspaceContext(query: String, maxFiles: Int, maxTotalChars: Int): String {
        val tokens = query.lowercase().split(Regex("[^a-z0-9_./-]+"))
            .filter { it.length >= 3 }.toSet()
        val candidates = workspaceFiles().filter { isTextWorkspaceFile(it) && it.length() <= MAX_CONTEXT_FILE_BYTES }
            .map { file ->
                val path = relativeWorkspacePath(file)
                val lowerPath = path.lowercase()
                val score = tokens.sumOf { token -> if (lowerPath.contains(token)) 5 else 0 } +
                    if (query.contains(path, ignoreCase = true)) 100 else 0
                file to score
            }
            .sortedWith(compareByDescending<Pair<File, Int>> { it.second }.thenBy { relativeWorkspacePath(it.first) })

        val out = StringBuilder()
        var used = 0
        for ((file, _) in candidates.take(maxFiles)) {
            val text = try { file.readText(Charsets.UTF_8) } catch (_: Throwable) { continue }
            val remaining = maxTotalChars - used
            if (remaining <= 0) break
            val clipped = text.take(minOf(remaining, MAX_CONTEXT_CHARS_PER_FILE))
            out.append("\n# FILE: ${relativeWorkspacePath(file)}\n")
            out.append(clipped)
            out.append("\n# END FILE\n")
            used += clipped.length
        }
        return out.toString()
    }

    private fun workspaceFiles(): List<File> = if (!workspaceDir.exists()) emptyList() else
        workspaceDir.walkTopDown().filter { it.isFile }.sortedBy { relativeWorkspacePath(it) }.toList()

    private fun workspaceHasFiles(): Boolean = workspaceFiles().isNotEmpty()

    private fun relativeWorkspacePath(file: File): String = file.relativeTo(workspaceDir).invariantSeparatorsPath

    private fun safeWorkspaceFile(relative: String): File {
        val file = File(workspaceDir, relative)
        val root = workspaceDir.canonicalPath + File.separator
        if (!file.canonicalPath.startsWith(root)) error("Unsafe workspace path")
        return file
    }

    private fun isTextWorkspaceFile(file: File): Boolean {
        val name = file.name.lowercase()
        return TEXT_EXTENSIONS.any { name.endsWith(it) }
    }

    // ---------------- DIAGNOSTICS ----------------

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
                    val modes = if (index % 2 == 0) listOf("RAW", "HIVE") else listOf("HIVE", "RAW")
                    for (mode in modes) {
                        withContext(Dispatchers.Main) { statusTv.text = "${benchCase.target / 1000}k • $mode • processing" }
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
        engine.setSystemPrompt(bundle.systemPrompt)
        val tempStart = batteryTempC()
        val memStart = availableMemoryBytes()
        val start = SystemClock.elapsedRealtime()
        val output = StringBuilder()
        engine.sendUserPrompt(prompt, predictLength = 64).collect { token -> output.append(token) }
        val elapsed = SystemClock.elapsedRealtime() - start
        val text = output.toString().trim()
        return RunResult(
            target = benchCase.target,
            mode = mode,
            promptTokens = promptTokens,
            elapsedMs = elapsed,
            passed = text.contains(bundle.expectedCommand),
            output = text,
            batteryStartC = tempStart,
            batteryEndC = batteryTempC(),
            availableRamStart = memStart,
            availableRamEnd = availableMemoryBytes(),
        )
    }

    private fun summaryFor(targets: List<Int>): String {
        val rows = targets.mapNotNull { target ->
            val raw = results.lastOrNull { it.target == target && it.mode == "RAW" }
            val hive = results.lastOrNull { it.target == target && it.mode == "HIVE" }
            if (raw == null || hive == null) return@mapNotNull null
            val reduction = if (raw.promptTokens > 0) 100.0 * (raw.promptTokens - hive.promptTokens) / raw.promptTokens else 0.0
            "${target / 1000}k: Raw=${if (raw.passed) "PASS" else "FAIL"} ${raw.elapsedMs}ms | Hive=${if (hive.passed) "PASS" else "FAIL"} ${hive.elapsedMs}ms | tokens ${raw.promptTokens}→${hive.promptTokens} (${String.format("%.1f", reduction)}% less)"
        }
        return "A/B SUMMARY\n" + rows.joinToString("\n")
    }

    private fun formatRun(run: RunResult): String = buildString {
        append("\n${run.target / 1000}k ${run.mode}: ${if (run.passed) "PASS" else "FAIL"}\n")
        append("prompt=${run.promptTokens} tokens • elapsed=${run.elapsedMs} ms")
        if (run.batteryStartC != null && run.batteryEndC != null) append(" • battery=${run.batteryStartC}→${run.batteryEndC}°C")
        append("\n${run.output.take(1200)}\n")
    }

    private fun shareResults() {
        if (results.isEmpty()) return
        val root = JSONObject()
        root.put("schema", "hive.phone-bench-result.v2")
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
            putExtra(Intent.EXTRA_SUBJECT, "Hive Mobile diagnostic result")
            putExtra(Intent.EXTRA_TEXT, root.toString(2))
        }
        startActivity(Intent.createChooser(intent, "Share Hive result"))
    }

    // ---------------- COMMON ----------------

    private suspend fun collectModel(prompt: String, predictLength: Int): String {
        val output = StringBuilder()
        engine.sendUserPrompt(prompt, predictLength = predictLength).collect { token -> output.append(token) }
        return output.toString().trim()
    }

    private fun setBusy(busy: Boolean, message: String) {
        progress.visibility = if (busy) View.VISIBLE else View.GONE
        statusTv.text = message
        selectModelBtn.isEnabled = !busy && engineReady
        modelPageBtn.isEnabled = !busy
        cancelBtn.isEnabled = busy
        importZipBtn.isEnabled = !busy
        clearWorkspaceBtn.isEnabled = !busy
        clearChatBtn.isEnabled = !busy
        if (modelFile != null) setModelActionsEnabled(!busy)
    }

    private fun setModelActionsEnabled(enabled: Boolean) {
        sendChatBtn.isEnabled = enabled
        planTaskBtn.isEnabled = enabled && workspaceHasFiles()
        proposeChangeBtn.isEnabled = enabled && workspaceHasFiles() && workPlan.isNotBlank()
        applyChangeBtn.isEnabled = enabled && pendingProposal != null
        rejectChangeBtn.isEnabled = enabled && pendingProposal != null
        throughputBtn.isEnabled = enabled
        runAllBtn.isEnabled = enabled
        run8Btn.isEnabled = enabled
        run16Btn.isEnabled = enabled
        run24Btn.isEnabled = enabled
        run30Btn.isEnabled = enabled
        shareBtn.isEnabled = enabled && results.isNotEmpty()
        exportZipBtn.isEnabled = !progress.isShown && workspaceHasFiles()
    }

    private fun restorePersistentState() {
        hiveStateCapsule = prefs.getString("hive_state", "{}") ?: "{}"
        val rawMessages = prefs.getString("chat_messages", "[]") ?: "[]"
        try {
            val array = JSONArray(rawMessages)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                chatMessages.add(ChatMessage(
                    id = obj.optString("id", "m${i + 1}"),
                    role = obj.optString("role", "user"),
                    text = obj.optString("text", ""),
                    createdAt = obj.optLong("created_at", 0L),
                ))
            }
        } catch (_: Throwable) {
            chatMessages.clear()
        }
        projectName = prefs.getString("project_name", "") ?: ""
        workPlan = prefs.getString("work_plan", "") ?: ""
        taskInput.setText(prefs.getString("work_task", "") ?: "")
        if (workPlan.isNotBlank()) workOutputTv.text = "RESTORED PLAN\n$workPlan"
    }

    private fun extractJsonObject(text: String): String? {
        val start = text.indexOf('{')
        val end = text.lastIndexOf('}')
        return if (start >= 0 && end > start) text.substring(start, end + 1) else null
    }

    private fun queryDisplayName(uri: Uri): String? {
        var cursor: Cursor? = null
        return try {
            cursor = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            if (cursor != null && cursor.moveToFirst()) cursor.getString(0) else null
        } finally { cursor?.close() }
    }

    private fun queryFileSize(uri: Uri): Long? {
        var cursor: Cursor? = null
        return try {
            cursor = contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)
            if (cursor != null && cursor.moveToFirst() && !cursor.isNull(0)) cursor.getLong(0) else null
        } catch (_: Throwable) { null } finally { cursor?.close() }
    }

    private fun safeProjectName(): String = projectName.ifBlank { "workspace" }.replace(Regex("[^A-Za-z0-9._-]+"), "-")

    private fun sha256(text: String): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }

    private fun appendResult(text: String) { resultTv.append(text) }

    private fun deviceSummary(): String {
        val activityManager = getSystemService(ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo().also { activityManager.getMemoryInfo(it) }
        return "${Build.MANUFACTURER} ${Build.MODEL} • Android ${Build.VERSION.RELEASE} • ${Runtime.getRuntime().availableProcessors()} CPUs • RAM ${formatBytes(info.totalMem)}"
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

    private fun loadBundle(): BenchBundle {
        val root = JSONObject(assets.open("hive_bench_cases.json").bufferedReader().use { it.readText() })
        val array = root.getJSONArray("cases")
        val cases = buildList {
            for (i in 0 until array.length()) {
                val c = array.getJSONObject(i)
                add(BenchCase(
                    target = c.getInt("target"),
                    rawPrompt = c.getString("raw_prompt"),
                    hivePrompt = c.getString("hive_prompt"),
                    rawTokens = c.getInt("raw_tokens"),
                    hiveTokens = c.getInt("hive_tokens"),
                ))
            }
        }
        return BenchBundle(
            benchmark = root.getString("benchmark"),
            expectedCommand = root.getString("expected_command"),
            systemPrompt = root.getString("system_prompt"),
            cases = cases,
        )
    }

    override fun onDestroy() {
        runJob?.cancel()
        if (engineReady) engine.destroy()
        super.onDestroy()
    }

    companion object {
        private const val QWEN_MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/blob/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
        private const val MAX_MODEL_BYTES = 6L * 1024L * 1024L * 1024L
        private const val MAX_WORKSPACE_BYTES = 150L * 1024L * 1024L
        private const val MAX_CONTEXT_FILE_BYTES = 250L * 1024L
        private const val MAX_CONTEXT_CHARS_PER_FILE = 12_000
        private const val MAX_REPLACEMENT_CHARS = 120_000
        private const val MAX_ZIP_ENTRIES = 2_000
        private const val MAX_MANIFEST_FILES = 300

        private val TEXT_EXTENSIONS = setOf(
            ".py", ".kt", ".java", ".js", ".ts", ".tsx", ".jsx", ".json", ".xml",
            ".md", ".txt", ".yml", ".yaml", ".toml", ".gradle", ".kts", ".properties",
            ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go", ".sh"
        )

        private const val CHAT_SYSTEM_PROMPT = """You are the local reasoning engine inside Hive Mobile. Human messages are source evidence and must never be silently rewritten. A compact machine-state capsule may be supplied; treat it as derived interpretation, not as authority over exact source. Answer the user normally and concisely. Do not invent access to files, tools, the internet, or accounts."""

        private const val STATE_EXTRACTOR_SYSTEM_PROMPT = """You are Hive's state extractor, separate from the conversational response. Return JSON only. Preserve source lineage by referencing message IDs instead of copying or rewriting human prose. Schema: {\"active_goals\":[],\"constraints\":[],\"decisions\":[],\"unresolved\":[],\"source_refs\":[]}. Keep only currently relevant operational state. If uncertain, retain ambiguity rather than inventing facts."""

        private const val WORK_PLAN_SYSTEM_PROMPT = """You are the planning engine inside Hive Mobile's isolated coding workspace. The human task is authoritative. Use only files supplied in the manifest/source evidence. Produce a conservative, executable plan with: target file(s), intended change, risks, validation, and stop conditions. Do not say anything was changed; this is planning only. Prefer the smallest safe change."""

        private const val WORK_CHANGE_SYSTEM_PROMPT = """You are the patch proposal engine inside Hive Mobile. You may propose exactly one replacement of one existing text file. Return JSON only with keys target_file, reason, replacement. target_file MUST exactly match a supplied workspace path. replacement MUST be the complete new contents of that file. Do not touch any other file, do not use ../ paths, do not claim the change was applied, and do not output markdown fences."""
    }
}

data class ChatMessage(val id: String, val role: String, val text: String, val createdAt: Long)
data class WorkspaceProposal(val targetFile: String, val reason: String, val replacement: String)
data class BenchCase(val target: Int, val rawPrompt: String, val hivePrompt: String, val rawTokens: Int, val hiveTokens: Int)
data class BenchBundle(val benchmark: String, val expectedCommand: String, val systemPrompt: String, val cases: List<BenchCase>)
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
