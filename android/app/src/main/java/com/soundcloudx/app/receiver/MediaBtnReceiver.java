package com.soundcloudx.app.receiver;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.view.KeyEvent;

import com.soundcloudx.app.PlayerService;
import com.soundcloudx.app.ScLog;

/**
 * Receives headset / bluetooth media button events while no session is active
 * and forwards them to {@link PlayerService}.
 *
 * The receiver is declared in the manifest and referenced by
 * MediaSession#setMediaButtonReceiver, which is how the system knows which app
 * should take over when the user presses play on a headset.
 */
public class MediaBtnReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) {
            return;
        }
        String action = intent.getAction();
        if (Intent.ACTION_MEDIA_BUTTON.equals(action)) {
            KeyEvent event = intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT);
            if (event == null || event.getAction() != KeyEvent.ACTION_DOWN) {
                return;
            }
            String cmd;
            switch (event.getKeyCode()) {
                case KeyEvent.KEYCODE_MEDIA_PLAY:
                    cmd = PlayerService.CMD_RESUME;
                    break;
                case KeyEvent.KEYCODE_MEDIA_PAUSE:
                    cmd = PlayerService.CMD_PAUSE;
                    break;
                case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                case KeyEvent.KEYCODE_HEADSETHOOK:
                    cmd = PlayerService.CMD_TOGGLE;
                    break;
                case KeyEvent.KEYCODE_MEDIA_NEXT:
                    cmd = PlayerService.CMD_NEXT;
                    break;
                case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                    cmd = PlayerService.CMD_PREV;
                    break;
                case KeyEvent.KEYCODE_MEDIA_STOP:
                    cmd = PlayerService.CMD_STOP;
                    break;
                default:
                    return;
            }
            dispatch(context, cmd, null, 0);
        } else if (PlayerService.CMD_PLAY.equals(action)
                || PlayerService.CMD_TOGGLE.equals(action)) {
            dispatch(context, PlayerService.CMD_TOGGLE, null, 0);
        }
    }

    /**
     * Starts {@link PlayerService} with a command. Works on Android 7 with a
     * plain startService and uses startForegroundService on newer releases,
     * falling back gracefully when the system refuses a background start.
     */
    public static void dispatch(Context context, String cmd, com.soundcloudx.app.Track track,
                                int seekMs) {
        Intent i = new Intent(context, PlayerService.class);
        i.putExtra(PlayerService.EXTRA_CMD, cmd);
        if (track != null) {
            i.putExtra(PlayerService.EXTRA_TRACK, track);
        }
        if (seekMs != 0) {
            i.putExtra(PlayerService.EXTRA_SEEK, seekMs);
        }
        ScLog.d("dispatch " + cmd + " track=" + (track != null));
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(i);
            } else {
                context.startService(i);
            }
        } catch (Throwable t) {
            ScLog.e("cannot start player from receiver: " + t.getClass().getSimpleName());
            try {
                context.startService(i);
            } catch (Throwable t2) {
                ScLog.e("startService refused too");
            }
        }
    }
}
