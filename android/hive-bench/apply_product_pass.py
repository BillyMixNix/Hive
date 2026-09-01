from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "overlay" / "MainActivity.kt"
LAYOUT = ROOT / "overlay" / "activity_main.xml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing expected block: {label}")
    return text.replace(old, new, 1)


main = MAIN.read_text(encoding="utf-8")

main = replace_once(
    main,
    """    private lateinit var navChatBtn: Button\n    private lateinit var navWorkBtn: Button\n    private lateinit var navDiagBtn: Button\n""",
    """    private lateinit var navChatBtn: Button\n    private lateinit var navWorkBtn: Button\n    private lateinit var navMemoryBtn: Button\n    private lateinit var navDiagBtn: Button\n""",
    "nav memory declaration",
)

main = replace_once(
    main,
    """    private lateinit var clearChatBtn: Button\n\n    private lateinit var workPanel: LinearLayout\n""",
    """    private lateinit var clearChatBtn: Button\n\n    private lateinit var memoryPanel: LinearLayout\n    private lateinit var memoryStateEdit: EditText\n    private lateinit var memorySourcesTv: TextView\n    private lateinit var saveMemoryBtn: Button\n    private lateinit var rebuildMemoryBtn: Button\n    private lateinit var clearMemoryBtn: Button\n\n    private lateinit var workPanel: LinearLayout\n""",
    "memory fields",
)

main = replace_once(
    main,
    """    private lateinit var rejectChangeBtn: Button\n    private lateinit var clearWorkspaceBtn: Button\n""",
    """    private lateinit var rejectChangeBtn: Button\n    private lateinit var undoChangeBtn: Button\n    private lateinit var clearWorkspaceBtn: Button\n""",
    "undo field",
)

main = replace_once(
    main,
    """    private val workspaceDir by lazy { File(filesDir, \"workspace\") }\n    private val auditFile by lazy { File(filesDir, \"hive_work_audit.jsonl\") }\n""",
    """    private val workspaceDir by lazy { File(filesDir, \"workspace\") }\n    private val auditFile by lazy { File(filesDir, \"hive_work_audit.jsonl\") }\n    private val undoDir by lazy { File(filesDir, \"workspace_undo\") }\n    private val lastUndoFile by lazy { File(filesDir, \"workspace_last_undo.json\") }\n""",
    "undo storage",
)

main = replace_once(
    main,
    """        renderChat()\n        renderProjectStatus()\n        showPanel(\"chat\")\n""",
    """        renderChat()\n        renderMemory()\n        renderProjectStatus()\n        showPanel(\"chat\")\n""",
    "initial memory render",
)

main = replace_once(
    main,
    """        lifecycleScope.launch(Dispatchers.Default) {\n            engine = AiChat.getInferenceEngine(applicationContext)\n            engineReady = true\n            withContext(Dispatchers.Main) {\n                selectModelBtn.isEnabled = true\n                statusTv.text = \"Ready. Load Qwen2.5-Coder 3B Q4_K_M to start.\"\n            }\n        }\n""",
    """        lifecycleScope.launch(Dispatchers.Default) {\n            engine = AiChat.getInferenceEngine(applicationContext)\n            engineReady = true\n            val remembered = prefs.getString(\"last_model_path\", null)?.let(::File)\n            if (remembered?.isFile == true && remembered.length() in 1..MAX_MODEL_BYTES) {\n                try {\n                    engine.loadModel(remembered.absolutePath)\n                    modelFile = remembered\n                    withContext(Dispatchers.Main) {\n                        selectModelBtn.isEnabled = true\n                        modelTv.text = \"${remembered.name} • ${formatBytes(remembered.length())}\"\n                        statusTv.text = \"Local model restored automatically.\"\n                        setModelActionsEnabled(true)\n                    }\n                } catch (t: Throwable) {\n                    prefs.edit().remove(\"last_model_path\").apply()\n                    withContext(Dispatchers.Main) {\n                        selectModelBtn.isEnabled = true\n                        statusTv.text = \"Saved model could not be restored: ${t.message}\"\n                    }\n                }\n            } else {\n                withContext(Dispatchers.Main) {\n                    selectModelBtn.isEnabled = true\n                    statusTv.text = \"Ready. Load Qwen2.5-Coder 3B Q4_K_M to start.\"\n                }\n            }\n        }\n""",
    "automatic model restore",
)

main = replace_once(
    main,
    """        navChatBtn = findViewById(R.id.nav_chat)\n        navWorkBtn = findViewById(R.id.nav_work)\n        navDiagBtn = findViewById(R.id.nav_diag)\n""",
    """        navChatBtn = findViewById(R.id.nav_chat)\n        navWorkBtn = findViewById(R.id.nav_work)\n        navMemoryBtn = findViewById(R.id.nav_memory)\n        navDiagBtn = findViewById(R.id.nav_diag)\n""",
    "bind memory nav",
)

main = replace_once(
    main,
    """        clearChatBtn = findViewById(R.id.clear_chat)\n\n        workPanel = findViewById(R.id.work_panel)\n""",
    """        clearChatBtn = findViewById(R.id.clear_chat)\n\n        memoryPanel = findViewById(R.id.memory_panel)\n        memoryStateEdit = findViewById(R.id.memory_state_edit)\n        memorySourcesTv = findViewById(R.id.memory_sources)\n        saveMemoryBtn = findViewById(R.id.save_memory)\n        rebuildMemoryBtn = findViewById(R.id.rebuild_memory)\n        clearMemoryBtn = findViewById(R.id.clear_memory)\n\n        workPanel = findViewById(R.id.work_panel)\n""",
    "bind memory views",
)

main = replace_once(
    main,
    """        rejectChangeBtn = findViewById(R.id.reject_change)\n        clearWorkspaceBtn = findViewById(R.id.clear_workspace)\n""",
    """        rejectChangeBtn = findViewById(R.id.reject_change)\n        undoChangeBtn = findViewById(R.id.undo_change)\n        clearWorkspaceBtn = findViewById(R.id.clear_workspace)\n""",
    "bind undo",
)

main = replace_once(
    main,
    """        navChatBtn.setOnClickListener { showPanel(\"chat\") }\n        navWorkBtn.setOnClickListener { showPanel(\"work\") }\n        navDiagBtn.setOnClickListener { showPanel(\"diag\") }\n""",
    """        navChatBtn.setOnClickListener { showPanel(\"chat\") }\n        navWorkBtn.setOnClickListener { showPanel(\"work\") }\n        navMemoryBtn.setOnClickListener { showPanel(\"memory\"); renderMemory() }\n        navDiagBtn.setOnClickListener { showPanel(\"diag\") }\n""",
    "wire memory nav",
)

main = replace_once(
    main,
    """        clearChatBtn.setOnClickListener {\n            chatMessages.clear()\n            hiveStateCapsule = \"{}\"\n            saveChatState()\n            renderChat()\n            statusTv.text = \"Chat source history and derived Hive state cleared.\"\n        }\n\n        importZipBtn.setOnClickListener""",
    """        clearChatBtn.setOnClickListener {\n            chatMessages.clear()\n            hiveStateCapsule = \"{}\"\n            saveChatState()\n            renderChat()\n            statusTv.text = \"Chat source history and derived Hive state cleared.\"\n        }\n        saveMemoryBtn.setOnClickListener { saveEditedMemory() }\n        rebuildMemoryBtn.setOnClickListener { rebuildMemoryFromSource() }\n        clearMemoryBtn.setOnClickListener { clearDerivedMemory() }\n\n        importZipBtn.setOnClickListener""",
    "wire memory actions",
)

main = replace_once(
    main,
    """        rejectChangeBtn.setOnClickListener { rejectWorkspaceProposal() }\n        clearWorkspaceBtn.setOnClickListener { clearWorkspace() }\n""",
    """        rejectChangeBtn.setOnClickListener { rejectWorkspaceProposal() }\n        undoChangeBtn.setOnClickListener { undoLastWorkspaceChange() }\n        clearWorkspaceBtn.setOnClickListener { clearWorkspace() }\n""",
    "wire undo",
)

main = replace_once(
    main,
    """    private fun showPanel(panel: String) {\n        chatPanel.visibility = if (panel == \"chat\") View.VISIBLE else View.GONE\n        workPanel.visibility = if (panel == \"work\") View.VISIBLE else View.GONE\n        diagPanel.visibility = if (panel == \"diag\") View.VISIBLE else View.GONE\n    }\n""",
    """    private fun showPanel(panel: String) {\n        chatPanel.visibility = if (panel == \"chat\") View.VISIBLE else View.GONE\n        memoryPanel.visibility = if (panel == \"memory\") View.VISIBLE else View.GONE\n        workPanel.visibility = if (panel == \"work\") View.VISIBLE else View.GONE\n        diagPanel.visibility = if (panel == \"diag\") View.VISIBLE else View.GONE\n    }\n""",
    "show memory panel",
)

main = replace_once(
    main,
    """                engine.loadModel(destination.absolutePath)\n                modelFile = destination\n                withContext(Dispatchers.Main) {\n""",
    """                engine.loadModel(destination.absolutePath)\n                modelFile = destination\n                prefs.edit().putString(\"last_model_path\", destination.absolutePath).apply()\n                withContext(Dispatchers.Main) {\n""",
    "persist selected model",
)

main = replace_once(
    main,
    """        hiveStateTv.text = \"Hive state: $stateSize chars derived • exact source messages: $sourceCount\"\n    }\n\n    private fun nextMessageId()""",
    """        hiveStateTv.text = \"Hive state: $stateSize chars derived • exact source messages: $sourceCount\"\n        renderMemory()\n    }\n\n    private fun renderMemory() {\n        if (!::memoryStateEdit.isInitialized) return\n        memoryStateEdit.setText(hiveStateCapsule)\n        memorySourcesTv.text = if (chatMessages.isEmpty()) {\n            \"No exact source messages yet. Derived memory never replaces source text.\"\n        } else {\n            chatMessages.takeLast(40).joinToString(\"\\n\\n\") { message ->\n                val who = if (message.role == \"user\") \"USER\" else \"HIVE\"\n                \"${message.id} • $who\\n${message.text.take(240)}\"\n            }\n        }\n    }\n\n    private fun saveEditedMemory() {\n        val candidate = memoryStateEdit.text.toString().trim().ifBlank { \"{}\" }\n        try {\n            val parsed = JSONObject(candidate)\n            hiveStateCapsule = parsed.toString(2)\n            saveChatState()\n            renderMemory()\n            statusTv.text = \"Derived Hive state updated. Exact source messages unchanged.\"\n        } catch (t: Throwable) {\n            statusTv.text = \"Memory not saved: state must be a JSON object.\"\n        }\n    }\n\n    private fun rebuildMemoryFromSource() {\n        if (modelFile == null || chatMessages.isEmpty() || runJob?.isActive == true) return\n        setBusy(true, \"Rebuilding derived state from exact source messages…\")\n        runJob = lifecycleScope.launch(Dispatchers.Default) {\n            try {\n                hiveStateCapsule = \"{}\"\n                refreshHiveStateCapsule()\n                saveChatState()\n                withContext(Dispatchers.Main) {\n                    renderMemory()\n                    setBusy(false, \"Derived state rebuilt from source.\")\n                }\n            } catch (t: Throwable) {\n                withContext(Dispatchers.Main) { setBusy(false, \"Memory rebuild stopped: ${t.message}\") }\n            }\n        }\n    }\n\n    private fun clearDerivedMemory() {\n        hiveStateCapsule = \"{}\"\n        saveChatState()\n        renderMemory()\n        statusTv.text = \"Derived Hive state cleared. Exact source messages preserved.\"\n    }\n\n    private fun nextMessageId()""",
    "memory functions",
)

main = replace_once(
    main,
    """                workspaceDir.deleteRecursively()\n                workspaceDir.mkdirs()\n""",
    """                workspaceDir.deleteRecursively()\n                undoDir.deleteRecursively()\n                lastUndoFile.delete()\n                workspaceDir.mkdirs()\n""",
    "clear undo on import",
)

main = replace_once(
    main,
    """            val target = safeWorkspaceFile(proposal.targetFile)\n            val oldText = target.readText(Charsets.UTF_8)\n            target.writeText(proposal.replacement, Charsets.UTF_8)\n            appendAudit(\"applied\", proposal, oldText)\n""",
    """            val target = safeWorkspaceFile(proposal.targetFile)\n            val oldText = target.readText(Charsets.UTF_8)\n            createUndoCheckpoint(proposal, oldText)\n            target.writeText(proposal.replacement, Charsets.UTF_8)\n            appendAudit(\"applied\", proposal, oldText)\n""",
    "create undo checkpoint",
)

main = replace_once(
    main,
    """    private fun rejectWorkspaceProposal() {\n        val proposal = pendingProposal ?: return\n        appendAudit(\"rejected\", proposal, null)\n        pendingProposal = null\n        workOutputTv.text = \"Proposal rejected. Workspace unchanged.\"\n        statusTv.text = \"Proposal rejected\"\n        setModelActionsEnabled(modelFile != null)\n    }\n\n    private fun appendAudit""",
    """    private fun rejectWorkspaceProposal() {\n        val proposal = pendingProposal ?: return\n        appendAudit(\"rejected\", proposal, null)\n        pendingProposal = null\n        workOutputTv.text = \"Proposal rejected. Workspace unchanged.\"\n        statusTv.text = \"Proposal rejected\"\n        setModelActionsEnabled(modelFile != null)\n    }\n\n    private fun createUndoCheckpoint(proposal: WorkspaceProposal, oldText: String) {\n        undoDir.mkdirs()\n        val backup = File(undoDir, \"${System.currentTimeMillis()}.bak\")\n        backup.writeText(oldText, Charsets.UTF_8)\n        val meta = JSONObject().apply {\n            put(\"target_file\", proposal.targetFile)\n            put(\"backup_path\", backup.absolutePath)\n            put(\"expected_current_sha256\", sha256(proposal.replacement))\n            put(\"created_at\", System.currentTimeMillis())\n        }\n        lastUndoFile.writeText(meta.toString(), Charsets.UTF_8)\n        undoChangeBtn.isEnabled = true\n    }\n\n    private fun undoLastWorkspaceChange() {\n        if (!lastUndoFile.isFile) {\n            statusTv.text = \"Nothing to undo\"\n            return\n        }\n        try {\n            val meta = JSONObject(lastUndoFile.readText(Charsets.UTF_8))\n            val targetFile = meta.getString(\"target_file\")\n            val target = safeWorkspaceFile(targetFile)\n            val backup = File(meta.getString(\"backup_path\"))\n            if (!target.isFile || !backup.isFile) error(\"Undo checkpoint is incomplete\")\n            val current = target.readText(Charsets.UTF_8)\n            val expected = meta.getString(\"expected_current_sha256\")\n            if (sha256(current) != expected) error(\"File changed after the checkpoint; refusing unsafe undo\")\n            val restored = backup.readText(Charsets.UTF_8)\n            target.writeText(restored, Charsets.UTF_8)\n            auditFile.appendText(JSONObject().apply {\n                put(\"timestamp\", System.currentTimeMillis())\n                put(\"disposition\", \"undone\")\n                put(\"project\", projectName)\n                put(\"target_file\", targetFile)\n                put(\"restored_sha256\", sha256(restored))\n            }.toString() + \"\\n\", Charsets.UTF_8)\n            backup.delete()\n            lastUndoFile.delete()\n            undoChangeBtn.isEnabled = false\n            workOutputTv.text = \"UNDONE\\n$targetFile restored to its pre-apply contents.\"\n            statusTv.text = \"Last applied workspace change undone\"\n        } catch (t: Throwable) {\n            statusTv.text = \"Undo refused: ${t.message}\"\n        }\n    }\n\n    private fun appendAudit""",
    "undo functions",
)

main = replace_once(
    main,
    """        workspaceDir.deleteRecursively()\n        projectName = \"\"\n""",
    """        workspaceDir.deleteRecursively()\n        undoDir.deleteRecursively()\n        lastUndoFile.delete()\n        projectName = \"\"\n""",
    "clear undo with workspace",
)

main = replace_once(
    main,
    """        exportZipBtn.isEnabled = files.isNotEmpty()\n    }\n""",
    """        exportZipBtn.isEnabled = files.isNotEmpty()\n        undoChangeBtn.isEnabled = files.isNotEmpty() && lastUndoFile.isFile\n    }\n""",
    "render undo availability",
)

MAIN.write_text(main, encoding="utf-8")

layout = LAYOUT.read_text(encoding="utf-8")
layout = layout.replace("android:hintTextColor=", "android:textColorHint=")

old_nav = """        <Button\n            android:id=\"@+id/nav_diag\"\n            android:layout_width=\"match_parent\"\n            android:layout_height=\"50dp\"\n            android:layout_marginTop=\"10dp\"\n            android:background=\"@drawable/hive_button_outline\"\n            android:text=\"Diagnostics  •  Raw vs Hive  •  Throughput\"\n            android:textAllCaps=\"false\"\n            android:textColor=\"#8FB8CD\"\n            android:textSize=\"13sp\" />\n"""
new_nav = """        <LinearLayout\n            android:layout_width=\"match_parent\"\n            android:layout_height=\"wrap_content\"\n            android:layout_marginTop=\"10dp\"\n            android:orientation=\"horizontal\">\n\n            <Button\n                android:id=\"@+id/nav_memory\"\n                android:layout_width=\"0dp\"\n                android:layout_height=\"50dp\"\n                android:layout_weight=\"1\"\n                android:background=\"@drawable/hive_button_outline\"\n                android:text=\"Memory  •  state + sources\"\n                android:textAllCaps=\"false\"\n                android:textColor=\"#65E2D9\"\n                android:textSize=\"12sp\" />\n\n            <Button\n                android:id=\"@+id/nav_diag\"\n                android:layout_width=\"0dp\"\n                android:layout_height=\"50dp\"\n                android:layout_marginStart=\"10dp\"\n                android:layout_weight=\"1\"\n                android:background=\"@drawable/hive_button_outline\"\n                android:text=\"Diagnostics\"\n                android:textAllCaps=\"false\"\n                android:textColor=\"#8DCCFF\"\n                android:textSize=\"12sp\" />\n        </LinearLayout>\n"""
layout = replace_once(layout, old_nav, new_nav, "memory nav layout")

memory_panel = """\n        <!-- MEMORY -->\n        <LinearLayout\n            android:id=\"@+id/memory_panel\"\n            android:layout_width=\"match_parent\"\n            android:layout_height=\"wrap_content\"\n            android:layout_marginTop=\"18dp\"\n            android:background=\"@drawable/hive_card\"\n            android:orientation=\"vertical\"\n            android:visibility=\"gone\">\n\n            <TextView\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"wrap_content\"\n                android:text=\"Memory\"\n                android:textColor=\"#F5FAFF\"\n                android:textSize=\"24sp\"\n                android:textStyle=\"bold\" />\n\n            <TextView\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"wrap_content\"\n                android:layout_marginTop=\"2dp\"\n                android:text=\"Derived state is editable. Exact source messages remain separate and authoritative.\"\n                android:textColor=\"#87A1B4\"\n                android:textSize=\"12sp\" />\n\n            <EditText\n                android:id=\"@+id/memory_state_edit\"\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"wrap_content\"\n                android:layout_marginTop=\"12dp\"\n                android:background=\"@drawable/hive_input\"\n                android:fontFamily=\"monospace\"\n                android:gravity=\"top|start\"\n                android:hint=\"{}\"\n                android:inputType=\"textMultiLine|textNoSuggestions\"\n                android:maxLines=\"14\"\n                android:minLines=\"7\"\n                android:padding=\"14dp\"\n                android:textColor=\"#DFF8F5\"\n                android:textColorHint=\"#577083\"\n                android:textSize=\"12sp\" />\n\n            <LinearLayout\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"wrap_content\"\n                android:layout_marginTop=\"10dp\"\n                android:orientation=\"horizontal\">\n\n                <Button\n                    android:id=\"@+id/save_memory\"\n                    android:layout_width=\"0dp\"\n                    android:layout_height=\"50dp\"\n                    android:layout_weight=\"1\"\n                    android:background=\"@drawable/hive_button_teal\"\n                    android:text=\"Save state\"\n                    android:textAllCaps=\"false\"\n                    android:textColor=\"#FFFFFF\" />\n\n                <Button\n                    android:id=\"@+id/rebuild_memory\"\n                    android:layout_width=\"0dp\"\n                    android:layout_height=\"50dp\"\n                    android:layout_marginStart=\"8dp\"\n                    android:layout_weight=\"1\"\n                    android:background=\"@drawable/hive_button_outline\"\n                    android:text=\"Rebuild from source\"\n                    android:textAllCaps=\"false\"\n                    android:textColor=\"#8DCCFF\" />\n\n                <Button\n                    android:id=\"@+id/clear_memory\"\n                    android:layout_width=\"0dp\"\n                    android:layout_height=\"50dp\"\n                    android:layout_marginStart=\"8dp\"\n                    android:layout_weight=\"1\"\n                    android:background=\"@drawable/hive_button_outline\"\n                    android:text=\"Clear derived\"\n                    android:textAllCaps=\"false\"\n                    android:textColor=\"#FFB1B8\" />\n            </LinearLayout>\n\n            <TextView\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"wrap_content\"\n                android:layout_marginTop=\"16dp\"\n                android:text=\"SOURCE EVIDENCE\"\n                android:textColor=\"#5D8CA8\"\n                android:textSize=\"11sp\"\n                android:textStyle=\"bold\" />\n\n            <TextView\n                android:id=\"@+id/memory_sources\"\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"wrap_content\"\n                android:layout_marginTop=\"8dp\"\n                android:background=\"@drawable/hive_input\"\n                android:minHeight=\"150dp\"\n                android:padding=\"14dp\"\n                android:textColor=\"#B7C9D6\"\n                android:textIsSelectable=\"true\"\n                android:textSize=\"12sp\" />\n        </LinearLayout>\n\n"""
layout = replace_once(layout, "\n        <!-- WORK -->\n", memory_panel + "        <!-- WORK -->\n", "memory panel layout")

old_clear = """            <Button\n                android:id=\"@+id/clear_workspace\"\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"48dp\"\n                android:layout_marginTop=\"10dp\"\n                android:background=\"@drawable/hive_button_outline\"\n                android:text=\"Clear workspace\"\n                android:textAllCaps=\"false\"\n                android:textColor=\"#8095A6\" />\n"""
new_clear = """            <Button\n                android:id=\"@+id/undo_change\"\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"48dp\"\n                android:layout_marginTop=\"10dp\"\n                android:background=\"@drawable/hive_button_outline\"\n                android:enabled=\"false\"\n                android:text=\"Undo last applied change\"\n                android:textAllCaps=\"false\"\n                android:textColor=\"#F4C878\" />\n\n            <Button\n                android:id=\"@+id/clear_workspace\"\n                android:layout_width=\"match_parent\"\n                android:layout_height=\"48dp\"\n                android:layout_marginTop=\"8dp\"\n                android:background=\"@drawable/hive_button_outline\"\n                android:text=\"Clear workspace\"\n                android:textAllCaps=\"false\"\n                android:textColor=\"#8095A6\" />\n"""
layout = replace_once(layout, old_clear, new_clear, "undo button layout")

LAYOUT.write_text(layout, encoding="utf-8")
print("Hive Mobile product pass applied")
