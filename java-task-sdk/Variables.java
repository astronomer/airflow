import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

import org.json.JSONObject;

public class Variables {
    private final Map<String, String> vars;

    public Variables() {
        this.vars = new HashMap<>();
    }

    public void put(String name, String value) {
        vars.put(name, value);
    }

    public String get(String name) {
        return vars.get(name);
    }

    @Override
    public String toString() {
        return vars.toString();
    }

    public JSONObject toJson() {
        return new JSONObject(vars);
    }

    public static Variables fromJson(JSONObject json) {
        Variables v = new Variables();
        for (String key : json.keySet()) {
            v.put(key, json.getString(key));
        }
        return v;
    }

    public void writeToFile(String filePath) throws IOException {
        try (FileWriter fw = new FileWriter(filePath)) {
            fw.write(toJson().toString(2));
        }
    }

    public static Variables fromFile(String filePath) throws IOException {
        File file = new File(filePath);
        if (!file.exists()) return new Variables();
        String content = Files.readString(file.toPath());
        return fromJson(new JSONObject(content));
    }
}

