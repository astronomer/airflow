import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

import org.json.JSONObject;

public class XcomData {
    private final Map<String, String> data;

    public XcomData() {
        this.data = new HashMap<>();
    }

    public void put(String name, String value) {
        data.put(name, value);
    }

    public String get(String name) {
        return data.get(name);
    }

    @Override
    public String toString() {
        return data.toString();
    }

    public JSONObject toJson() {
        return new JSONObject(data);
    }

    public static XcomData fromJson(JSONObject json) {
        XcomData xcom = new XcomData();
        for (String key : json.keySet()) {
            xcom.put(key, json.getString(key));
        }
        return xcom;
    }

    public void writeToFile(String filePath) throws IOException {
        try (FileWriter fw = new FileWriter(filePath)) {
            fw.write(toJson().toString(2));
        }
    }

    public static XcomData fromFile(String filePath) throws IOException {
        File file = new File(filePath);
        if (!file.exists()) return new XcomData();
        String content = Files.readString(file.toPath());
        return fromJson(new JSONObject(content));
    }
}

