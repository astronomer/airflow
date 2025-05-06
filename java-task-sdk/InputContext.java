public class InputContext {
    private final XcomData xcomData;
    private final Variables variables;

    public InputContext(XcomData xcomData, Variables variables) {
        this.xcomData = xcomData;
        this.variables = variables;
    }

    public String getXcom(String name) {
        return xcomData.get(name);
    }

    public String getVariable(String name) {
        return variables.get(name);
    }

    @Override
    public String toString() {
        return "InputContext{" +
               "xcomData=" + xcomData +
               ", variables=" + variables +
               '}';
    }
}

