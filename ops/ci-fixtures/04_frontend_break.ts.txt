// Breaks: Angular build (references a symbol that does not exist)
import { NonExistentThing } from '@angular/core';
export const broken = new NonExistentThing();
