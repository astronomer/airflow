JAVAC=javac
JAVA=java
SRC=*.java
MAIN_CLASS=Main

# Set classpath to include current directory and all jars in lib/
CP=.:lib/*

# Compile all Java files
build:
	$(JAVAC) -cp "$(CP)" $(SRC)

# Run the main class
run:
	$(JAVA) -cp "$(CP)" $(MAIN_CLASS)

# Clean up .class files and temp files
clean:
	rm -f *.class xcom_*.json vars_*.json

