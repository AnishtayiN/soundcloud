package com.soundcloudx.app;

import android.app.Activity;
import android.graphics.Bitmap;
import android.text.TextUtils;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.TextView;

import java.util.List;

/** Renders one SoundCloud track per row with a lazily loaded cover. */
public class TrackAdapter extends BaseAdapter {

    public interface RowMenuListener {
        void onRowMenu(Track track, int position, View anchor);
    }

    private final Activity activity;
    private final List<Track> tracks;
    private final RowMenuListener menuListener;

    public TrackAdapter(Activity activity, List<Track> tracks, RowMenuListener menuListener) {
        this.activity = activity;
        this.tracks = tracks;
        this.menuListener = menuListener;
    }

    @Override
    public int getCount() {
        return tracks.size();
    }

    @Override
    public Object getItem(int position) {
        return tracks.get(position);
    }

    @Override
    public long getItemId(int position) {
        return tracks.get(position).id;
    }

    @Override
    public View getView(int position, View convertView, ViewGroup parent) {
        View view = convertView;
        if (view == null) {
            view = LayoutInflater.from(activity).inflate(R.layout.row_track, parent, false);
            view.setTag(R.id.imgArt, view.findViewById(R.id.imgArt));
        }
        final Track track = tracks.get(position);

        ImageView art = (ImageView) view.getTag(R.id.imgArt);
        TextView title = (TextView) view.findViewById(R.id.txtTitle);
        TextView sub = (TextView) view.findViewById(R.id.txtSub);
        ImageButton menu = (ImageButton) view.findViewById(R.id.btnRowMenu);

        title.setText(track.title);
        sub.setText(subtitle(track));

        if (art != null) {
            final String url = track.thumbUrl();
            final ImageView artView = art;
            art.setTag(url);
            art.setImageBitmap(null);
            Bitmap cached = Art.memory(url);
            if (cached != null) {
                art.setImageBitmap(cached);
            } else if (!TextUtils.isEmpty(url)) {
                Art.load(activity, url, new Art.Callback() {
                    @Override
                    public void ready(Bitmap bitmap) {
                        // Ignore answers for rows that have been recycled.
                        if (bitmap != null && url.equals(artView.getTag())) {
                            artView.setImageBitmap(bitmap);
                        }
                    }
                });
            }
        }

        final int index = position;
        menu.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (menuListener != null) {
                    menuListener.onRowMenu(track, index, v);
                }
            }
        });
        return view;
    }

    private String subtitle(Track t) {
        StringBuilder sb = new StringBuilder();
        if (!TextUtils.isEmpty(t.artist)) {
            sb.append(t.artist);
        }
        if (t.durationMs > 0) {
            sb.append(sb.length() == 0 ? "" : "  •  ").append(t.durationText());
        }
        String plays = Fmt.plays(t.plays);
        if (!TextUtils.isEmpty(plays)) {
            sb.append(sb.length() == 0 ? "" : "  •  ").append("▶ ").append(plays);
        }
        if (t.downloadable) {
            sb.append("  •  ⬇ original");
        }
        if (!t.streamable) {
            sb.append("  •  ⚠");
        }
        return sb.toString();
    }
}
