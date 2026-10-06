package dev.atmcompanion.state;

import com.google.gson.annotations.SerializedName;

public enum CapabilityStatus {
    @SerializedName("available") AVAILABLE,
    @SerializedName("unavailable") UNAVAILABLE,
    @SerializedName("not_integrated") NOT_INTEGRATED
}
