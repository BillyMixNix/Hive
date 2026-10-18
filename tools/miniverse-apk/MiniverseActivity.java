package com.winlator;

import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import com.winlator.container.Container;
import com.winlator.container.ContainerManager;
import com.winlator.xenvironment.RootFS;
import com.winlator.xenvironment.RootFSInstaller;

import java.io.File;

public class MiniverseActivity extends MainActivity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private int waits = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Miniverse Minigolf");
        handler.postDelayed(this::launchWhenReady, 750);
    }

    private void launchWhenReady() {
        RootFS rootFS = RootFS.find(this);
        if (!rootFS.isValid() || rootFS.getVersion() < RootFSInstaller.LATEST_VERSION) {
            if (++waits > 300) {
                Toast.makeText(this, "Miniverse runtime installation did not complete.", Toast.LENGTH_LONG).show();
                return;
            }
            handler.postDelayed(this::launchWhenReady, 1000);
            return;
        }

        ContainerManager manager = new ContainerManager(this);
        Container container = manager.getContainerById(1);
        if (container == null) {
            Toast.makeText(this, "Miniverse runtime container is missing.", Toast.LENGTH_LONG).show();
            return;
        }

        File exe = new File(container.getRootDir(), ".wine/drive_c/Miniverse/Miniverse.exe");
        if (!exe.isFile()) {
            Toast.makeText(this, "Miniverse.exe is missing.", Toast.LENGTH_LONG).show();
            return;
        }

        Intent intent = new Intent(this, XServerDisplayActivity.class);
        intent.putExtra("container_id", container.id);
        intent.putExtra("exec_path", exe.getAbsolutePath());
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(intent);
        finish();
    }
}
