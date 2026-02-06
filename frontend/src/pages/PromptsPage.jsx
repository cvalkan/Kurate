import { useState, useEffect } from "react";
import { toast } from "sonner";
import axios from "axios";
import { 
  Save, 
  RotateCcw, 
  Copy, 
  Check,
  FileText,
  MessageSquare,
  Sparkles,
  Beaker,
  Target,
  Lightbulb,
  Users
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const promptIcons = {
  scientific_impact_predicted: Users,
  scientific_impact: Sparkles,
  practical_applications: Target,
  technical_novelty: Lightbulb,
  research_rigor: Beaker
};

export default function PromptsPage() {
  const [prompts, setPrompts] = useState([]);
  const [editedPrompts, setEditedPrompts] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState({});
  const [copiedField, setCopiedField] = useState(null);
  const [activeTab, setActiveTab] = useState("scientific_impact");

  useEffect(() => {
    fetchPrompts();
  }, []);

  const fetchPrompts = async () => {
    try {
      const response = await axios.get(`${API}/prompts`);
      setPrompts(response.data.prompts);
      // Initialize edited prompts with current values
      const edited = {};
      response.data.prompts.forEach(p => {
        edited[p.key] = {
          system_prompt: p.system_prompt,
          user_prompt: p.user_prompt,
          modified: false
        };
      });
      setEditedPrompts(edited);
    } catch (error) {
      toast.error("Failed to load prompts");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handlePromptChange = (key, field, value) => {
    setEditedPrompts(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        [field]: value,
        modified: true
      }
    }));
  };

  const handleSave = async (key) => {
    setSaving(prev => ({ ...prev, [key]: true }));
    try {
      await axios.put(`${API}/prompts/${key}`, {
        system_prompt: editedPrompts[key].system_prompt,
        user_prompt: editedPrompts[key].user_prompt
      });
      setEditedPrompts(prev => ({
        ...prev,
        [key]: { ...prev[key], modified: false }
      }));
      toast.success("Prompt saved successfully!");
    } catch (error) {
      toast.error("Failed to save prompt");
      console.error(error);
    } finally {
      setSaving(prev => ({ ...prev, [key]: false }));
    }
  };

  const handleReset = async (key) => {
    try {
      await axios.delete(`${API}/prompts/${key}`);
      // Refetch to get default values
      await fetchPrompts();
      toast.success("Prompt reset to default!");
    } catch (error) {
      toast.error("Failed to reset prompt");
      console.error(error);
    }
  };

  const copyToClipboard = (text, field) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
    toast.success("Copied to clipboard!");
  };

  if (loading) {
    return (
      <div className="container-main py-8">
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="container-main py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-heading font-bold mb-2">Evaluation Prompts</h1>
        <p className="text-muted-foreground">
          Customize how the AI evaluates and compares scientific papers. Each prompt defines the criteria used during tournament comparisons.
        </p>
      </div>

      {/* Info Card */}
      <Card className="mb-6 bg-accent/5 border-accent/20">
        <CardContent className="pt-4">
          <div className="flex gap-3">
            <FileText className="h-5 w-5 text-accent flex-shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium mb-1">How prompts work:</p>
              <ul className="text-muted-foreground space-y-1">
                <li>• <strong>System Prompt:</strong> Sets the AI's role and evaluation criteria</li>
                <li>• <strong>User Prompt:</strong> Template for each comparison (uses {'{paper1_title}'}, {'{paper1_abstract}'}, etc.)</li>
                <li>• Changes apply to new tournaments only</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Prompts Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid grid-cols-2 lg:grid-cols-4 w-full h-auto gap-2 bg-transparent p-0">
          {prompts.map(prompt => {
            const Icon = promptIcons[prompt.key] || FileText;
            const isModified = editedPrompts[prompt.key]?.modified;
            return (
              <TabsTrigger 
                key={prompt.key} 
                value={prompt.key}
                className="flex items-center gap-2 data-[state=active]:bg-accent data-[state=active]:text-accent-foreground px-4 py-3 border rounded-lg"
                data-testid={`tab-${prompt.key}`}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{prompt.name.replace(' (Default)', '')}</span>
                <span className="sm:hidden">{prompt.name.split(' ')[0]}</span>
                {isModified && (
                  <span className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0" />
                )}
              </TabsTrigger>
            );
          })}
        </TabsList>

        {prompts.map(prompt => {
          const Icon = promptIcons[prompt.key] || FileText;
          const edited = editedPrompts[prompt.key] || {};
          const isModified = edited.modified;

          return (
            <TabsContent key={prompt.key} value={prompt.key} className="space-y-6">
              <Card>
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-accent/10">
                        <Icon className="h-5 w-5 text-accent" />
                      </div>
                      <div>
                        <CardTitle className="text-xl flex items-center gap-2">
                          {prompt.name}
                          {prompt.is_default && (
                            <Badge variant="outline" className="text-xs">Default</Badge>
                          )}
                          {isModified && (
                            <Badge variant="outline" className="text-xs border-amber-300 text-amber-700 bg-amber-50">
                              Modified
                            </Badge>
                          )}
                        </CardTitle>
                        <CardDescription className="mt-1">
                          {prompt.description}
                        </CardDescription>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="outline" size="sm" data-testid={`reset-${prompt.key}`}>
                            <RotateCcw className="h-4 w-4 mr-1" />
                            Reset
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Reset to Default?</AlertDialogTitle>
                            <AlertDialogDescription>
                              This will restore the original prompt for "{prompt.name}". Any custom changes will be lost.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleReset(prompt.key)}>
                              Reset
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                      <Button 
                        onClick={() => handleSave(prompt.key)}
                        disabled={!isModified || saving[prompt.key]}
                        data-testid={`save-${prompt.key}`}
                      >
                        <Save className="h-4 w-4 mr-1" />
                        {saving[prompt.key] ? "Saving..." : "Save"}
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* System Prompt */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-base font-medium flex items-center gap-2">
                        <MessageSquare className="h-4 w-4" />
                        System Prompt
                      </Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => copyToClipboard(edited.system_prompt, `${prompt.key}-system`)}
                      >
                        {copiedField === `${prompt.key}-system` ? (
                          <Check className="h-4 w-4 text-green-500" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground mb-2">
                      Defines the AI's role and evaluation criteria. This sets the context for all comparisons.
                    </p>
                    <Textarea
                      value={edited.system_prompt || ''}
                      onChange={(e) => handlePromptChange(prompt.key, 'system_prompt', e.target.value)}
                      className="min-h-[200px] font-mono text-sm"
                      placeholder="Enter system prompt..."
                      data-testid={`system-prompt-${prompt.key}`}
                    />
                  </div>

                  {/* User Prompt */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-base font-medium flex items-center gap-2">
                        <FileText className="h-4 w-4" />
                        User Prompt Template
                      </Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => copyToClipboard(edited.user_prompt, `${prompt.key}-user`)}
                      >
                        {copiedField === `${prompt.key}-user` ? (
                          <Check className="h-4 w-4 text-green-500" />
                        ) : (
                          <Copy className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground mb-2">
                      Template for each comparison. Available variables: <code className="bg-muted px-1 rounded">{'{paper1_title}'}</code>, <code className="bg-muted px-1 rounded">{'{paper1_abstract}'}</code>, <code className="bg-muted px-1 rounded">{'{paper2_title}'}</code>, <code className="bg-muted px-1 rounded">{'{paper2_abstract}'}</code>
                    </p>
                    <Textarea
                      value={edited.user_prompt || ''}
                      onChange={(e) => handlePromptChange(prompt.key, 'user_prompt', e.target.value)}
                      className="min-h-[180px] font-mono text-sm"
                      placeholder="Enter user prompt template..."
                      data-testid={`user-prompt-${prompt.key}`}
                    />
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}
